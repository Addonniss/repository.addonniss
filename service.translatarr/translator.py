# -*- coding: utf-8 -*-
import requests
import re
import xbmc
import xbmcaddon

ADDON = xbmcaddon.Addon('service.translatarr')


# ----------------------------------------------------------
# Logging
# ----------------------------------------------------------
def log(msg):
    xbmc.log(f"[Translatarr] {msg}", xbmc.LOGINFO)


# ----------------------------------------------------------
# Style Builder (uses new setting: translation_style)
# ----------------------------------------------------------
def build_style_instruction(trg_name):
    style_mode = ADDON.getSetting('translation_style')

    # 0 = Family-Friendly (default)
    # 1 = Natural
    # 2 = Gritty / Adult

    if style_mode == "Gritty / Adult":
        return (
            "STYLE REQUIREMENT:\n"
            f"- Tone: gritty, raw, adult {trg_name}.\n"
            "- Preserve profanity and strong language.\n"
            "- Do NOT soften insults.\n"
            "- Maintain emotional intensity.\n"
        )

    elif style_mode == "Natural":
        return (
            "STYLE REQUIREMENT:\n"
            f"- Tone: natural conversational {trg_name}.\n"
            "- Sound realistic and fluid.\n"
            "- Avoid overly literal translation.\n"
            "- Always translate the dialogue, even when the source contains profanity or strong insults.\n"
            "- Render profanity and insults naturally for the target language without intensifying them.\n"
        )

    # Default = Family-Friendly
    return (
        "STYLE REQUIREMENT:\n"
        f"- Tone: clean, neutral, broadcast-safe {trg_name}.\n"
        "- Always translate the dialogue, even when the source contains profanity or strong insults.\n"
        "- Render profanity and strong insults as mild, non-profane alternatives.\n"
        "- Keep dialogue suitable for general audiences.\n"
    )


def build_localization_instruction():
    return (
        "LOCALIZATION REQUIREMENT:\n"
        "- Translate idiomatic expressions by meaning rather than word-for-word when needed.\n"
        "- Use context to choose grammatical gender correctly when the target language requires it.\n"
    )


def build_source_context_block(context_list):
    if not context_list:
        return ""

    prefixed = [f"C{i:03}: {t}" for i, t in enumerate(context_list)]
    return (
        "READ-ONLY SOURCE CONTEXT FROM PREVIOUS SUBTITLES:\n"
        "- Use these previous source lines only to understand references, pronouns, tone, and sentence continuity.\n"
        "- Do NOT translate these context lines.\n"
        "- Do NOT output Cxxx anchors.\n"
        + "\n".join(prefixed)
        + "\n\n"
        "CURRENT LINES TO TRANSLATE:\n"
    )

# ----------------------------------------------------------
# Base Translator
# ----------------------------------------------------------
class BaseTranslator:

    def _get_temperature(self, provider=None):
        setting_ids = []
        if provider == "Gemini":
            setting_ids.append('temp_gemini')
        elif provider == "OpenAI":
            setting_ids.append('temp_openai')
        elif provider == "Anthropic":
            setting_ids.append('temp_anthropic')
        elif provider == "DeepSeek":
            setting_ids.append('temp_deepseek')
        elif provider == "OpenRouter":
            setting_ids.append('temp_openrouter')

        # Backward compatibility for existing installs that already saved `temp`.
        setting_ids.append('temp')

        try:
            for setting_id in setting_ids:
                value = (ADDON.getSetting(setting_id) or '').strip()
                if not value:
                    continue

                temp = float(value)
                return max(0.0, min(temp, 1.0))
        except:
            pass

        return 0.15

    def _scrub(self, raw_text, expected):
        """
        Extract only Lxxx prefixed lines.
        Remove prefix and return clean list.
        Must match expected_count exactly.
        """
        if not raw_text:
            return None

        lines = raw_text.splitlines()
        cleaned = []

        for line in lines:
            match = re.match(r'^\s*L(\d{3}):\s*(.*)', line)
            if match:
                cleaned.append(match.group(2).strip())

        return cleaned if len(cleaned) == expected else None

    def translate_batch(self, text_list, expected_count, context_list=None):
        raise NotImplementedError

    def calculate_cost(self, input_tokens, output_tokens):
        raise NotImplementedError

    def get_model_string(self):
        raise NotImplementedError


# ==========================================================
# GEMINI TRANSLATOR
# ==========================================================
class GeminiTranslator(BaseTranslator):

    PRICING = {
        "gemini-3.1-flash-lite": (0.00000025, 0.0000015),
        "gemini-2.5-flash-lite": (0.0000001, 0.0000004),
    }

    def __init__(self):
        self.api_key = ADDON.getSetting('api_key')
        self.temperature = self._get_temperature("Gemini")

        model_map = {
            "Gemini 3.1 Flash-Lite": "gemini-3.1-flash-lite",
            "Gemini 2.5 Flash-Lite": "gemini-2.5-flash-lite"
        }

        selected_model = ADDON.getSetting('model')
        self.model = model_map.get(selected_model, "gemini-3.1-flash-lite")

        # Thinking level for Gemini 3.x models
        thinking_map = {
            "Minimal": "minimal",
            "Low": "low",
            "Medium": "medium",
            "High": "high",
        }
        raw_level = ADDON.getSetting('gemini_thinking_level') or "Minimal"
        self.thinking_level = thinking_map.get(raw_level, "minimal")
        self.is_gemini3 = self.model.startswith("gemini-3")

    def translate_batch(self, text_list, expected_count, context_list=None):

        if not self.api_key:
            log("Gemini API key missing")
            return None, 0, 0

        from languages import get_lang_params, get_active_language_setting
        src_name, _ = get_lang_params(get_active_language_setting(ADDON, "Gemini", 'source'))
        trg_name, _ = get_lang_params(get_active_language_setting(ADDON, "Gemini", 'target'))

        if src_name.lower() != "auto-detect":
            lang_instruction = f"Translate from {src_name} to {trg_name}."
        else:
            lang_instruction = f"Detect the source language and translate to {trg_name}."

        prefixed = [f"L{i:03}: {t}" for i, t in enumerate(text_list)]
        input_text = build_source_context_block(context_list) + "\n".join(prefixed)

        style_block = build_style_instruction(trg_name)
        localization_block = build_localization_instruction()

        url = (
            f"https://generativelanguage.googleapis.com/v1beta/models/"
            f"{self.model}:generateContent?key={self.api_key}"
        )

        payload = {
            "contents": [{
                "parts": [{
                    "text": (
                        "You are a professional subtitle localizer.\n"
                        f"{lang_instruction}\n\n"
                        "STRICT RULES (MANDATORY):\n"
                        "1. Preserve 'Lxxx:' anchors EXACTLY.\n"
                        f"2. Return EXACTLY {expected_count} lines.\n"
                        "3. Return ONLY prefixed translated lines.\n"
                        "4. Do NOT add commentary.\n\n"
                        "5. If read-only Cxxx source context is provided, use it for meaning only and never include it in the output.\n\n"
                        f"{localization_block}\n"
                        f"{style_block}\n"
                        f"{input_text}"
                    )
                }]
            }],
            "generationConfig": {
                "temperature": self.temperature
            }
        }

        if self.is_gemini3:
            payload["generationConfig"]["thinkingConfig"] = {
                "thinkingLevel": self.thinking_level
            }

        try:
            r = requests.post(url, json=payload, timeout=30)
            if r.status_code != 200:
                log(f"Gemini error ({self.model}): {r.status_code} | {r.text[:500]}")
                return None, 0, 0

            data = r.json()
            raw = (
                data.get("candidates", [{}])[0]
                .get("content", {})
                .get("parts", [{}])[0]
                .get("text", "")
                .strip()
            )

            translated = self._scrub(raw, expected_count)
            if not translated:
                log("Gemini scrub failed")
                return None, 0, 0

            usage = data.get("usageMetadata", {})
            in_t = usage.get("promptTokenCount", 0)
            out_t = usage.get("candidatesTokenCount", 0)

            return translated, in_t, out_t

        except Exception as e:
            log(f"Gemini exception ({self.model}): {e}")
            return None, 0, 0

    def calculate_cost(self, input_tokens, output_tokens):
        in_price, out_price = self.PRICING.get(self.model, (0, 0))
        return (input_tokens * in_price) + (output_tokens * out_price)

    def get_model_string(self):
        if self.is_gemini3:
            return f"Gemini ({self.model}, think={self.thinking_level})"
        return f"Gemini ({self.model})"


# ==========================================================
# OPENAI TRANSLATOR
# ==========================================================
class OpenAITranslator(BaseTranslator):

    PRICING = {
        "gpt-5.4-nano": (0.00000020, 0.00000125),
        "gpt-5-mini": (0.00000025, 0.0000020),
        "gpt-4o-mini": (0.00000015, 0.00000060),
    }

    def __init__(self):
        self.api_key = ADDON.getSetting('openai_api_key')
        self.temperature = self._get_temperature("OpenAI")

        model_map = {
            "gpt-5.4-nano": "gpt-5.4-nano",
            "gpt-5-mini": "gpt-5-mini",
            "gpt-4o-mini": "gpt-4o-mini",
        }

        self.model = model_map.get(ADDON.getSetting('openai_model'), "gpt-5.4-nano")
        self.is_gpt5 = self.model.startswith("gpt-5")

        # Reasoning effort for GPT-5 models
        reasoning_map = {
            "Minimal": "minimal",
            "Low": "low",
            "Medium": "medium",
            "High": "high",
        }
        raw_level = ADDON.getSetting('openai_reasoning_effort') or "Minimal"
        self.reasoning_effort = reasoning_map.get(raw_level, "minimal")

    def _supports_custom_temperature(self):
        return not self.model.startswith("gpt-5")

    def translate_batch(self, text_list, expected_count, context_list=None):

        if not self.api_key:
            log("OpenAI API key missing")
            return None, 0, 0

        from languages import get_lang_params, get_active_language_setting
        src_name, _ = get_lang_params(get_active_language_setting(ADDON, "OpenAI", 'source'))
        trg_name, _ = get_lang_params(get_active_language_setting(ADDON, "OpenAI", 'target'))

        if src_name.lower() != "auto-detect":
            lang_instruction = f"Translate from {src_name} to {trg_name}."
        else:
            lang_instruction = f"Detect the source language and translate to {trg_name}."

        prefixed = [f"L{i:03}: {t}" for i, t in enumerate(text_list)]
        input_text = build_source_context_block(context_list) + "\n".join(prefixed)

        style_block = build_style_instruction(trg_name)
        localization_block = build_localization_instruction()

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a professional subtitle localizer.\n"
                        f"{lang_instruction}\n\n"
                        "STRICT RULES (MANDATORY):\n"
                        "1. Preserve 'Lxxx:' anchors EXACTLY.\n"
                        f"2. Return EXACTLY {expected_count} lines.\n"
                        "3. Return ONLY prefixed translated lines.\n"
                        "4. Do NOT add commentary.\n\n"
                        "5. If read-only Cxxx source context is provided, use it for meaning only and never include it in the output.\n\n"
                        f"{localization_block}\n"
                        f"{style_block}"
                    )
                },
                {"role": "user", "content": input_text}
            ]
        }
        if self.is_gpt5:
            payload["reasoning_effort"] = self.reasoning_effort
        elif self._supports_custom_temperature():
            payload["temperature"] = self.temperature

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            r = requests.post(
                "https://api.openai.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )

            if r.status_code != 200:
                log(f"OpenAI error ({self.model}): {r.status_code} | {r.text[:500]}")
                return None, 0, 0

            data = r.json()
            raw = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

            translated = self._scrub(raw, expected_count)
            if not translated:
                log("OpenAI scrub failed")
                return None, 0, 0

            usage = data.get("usage", {})
            in_t = usage.get("prompt_tokens", 0)
            out_t = usage.get("completion_tokens", 0)

            return translated, in_t, out_t

        except Exception as e:
            log(f"OpenAI exception ({self.model}): {e}")
            return None, 0, 0

    def calculate_cost(self, input_tokens, output_tokens):
        in_price, out_price = self.PRICING.get(self.model, (0, 0))
        return (input_tokens * in_price) + (output_tokens * out_price)

    def get_model_string(self):
        if self.is_gpt5:
            return f"OpenAI ({self.model}, reason={self.reasoning_effort})"
        return f"OpenAI ({self.model})"


# ==========================================================
# ANTHROPIC TRANSLATOR
# ==========================================================
class AnthropicTranslator(BaseTranslator):

    PRICING = {
        "claude-haiku-4-5": (0.0000010, 0.0000050),
    }

    def __init__(self):
        self.api_key = ADDON.getSetting('anthropic_api_key')
        self.temperature = self._get_temperature("Anthropic")

        model_map = {
            "Claude Haiku": "claude-haiku-4-5",
        }

        self.model = model_map.get(
            ADDON.getSetting('anthropic_model'),
            "claude-haiku-4-5"
        )

    def translate_batch(self, text_list, expected_count, context_list=None):

        if not self.api_key:
            log("Anthropic API key missing")
            return None, 0, 0

        from languages import get_lang_params, get_active_language_setting
        src_name, _ = get_lang_params(get_active_language_setting(ADDON, "Anthropic", 'source'))
        trg_name, _ = get_lang_params(get_active_language_setting(ADDON, "Anthropic", 'target'))

        if src_name.lower() != "auto-detect":
            lang_instruction = f"Translate from {src_name} to {trg_name}."
        else:
            lang_instruction = f"Detect the source language and translate to {trg_name}."

        prefixed = [f"L{i:03}: {t}" for i, t in enumerate(text_list)]
        input_text = build_source_context_block(context_list) + "\n".join(prefixed)

        style_block = build_style_instruction(trg_name)
        localization_block = build_localization_instruction()

        payload = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": self.temperature,
            "system": (
                "You are a professional subtitle localizer.\n"
                f"{lang_instruction}\n\n"
                "STRICT RULES (MANDATORY):\n"
                "1. Preserve 'Lxxx:' anchors EXACTLY.\n"
                f"2. Return EXACTLY {expected_count} lines.\n"
                "3. Return ONLY prefixed translated lines.\n"
                "4. Do NOT add commentary.\n\n"
                "5. If read-only Cxxx source context is provided, use it for meaning only and never include it in the output.\n\n"
                f"{localization_block}\n"
                f"{style_block}"
            ),
            "messages": [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": input_text}
                    ]
                }
            ]
        }

        headers = {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json"
        }

        try:
            r = requests.post(
                "https://api.anthropic.com/v1/messages",
                headers=headers,
                json=payload,
                timeout=30
            )

            if r.status_code != 200:
                log(f"Anthropic error ({self.model}): {r.status_code} | {r.text[:500]}")
                return None, 0, 0

            data = r.json()
            content = data.get("content", [])
            text_parts = []
            for part in content:
                if str(part.get("type") or "").lower() == "text":
                    text_parts.append(part.get("text", ""))
            raw = "\n".join(text_parts).strip()

            translated = self._scrub(raw, expected_count)
            if not translated:
                log("Anthropic scrub failed")
                return None, 0, 0

            usage = data.get("usage", {})
            in_t = usage.get("input_tokens", 0)
            out_t = usage.get("output_tokens", 0)

            return translated, in_t, out_t

        except Exception as e:
            log(f"Anthropic exception ({self.model}): {e}")
            return None, 0, 0

    def calculate_cost(self, input_tokens, output_tokens):
        in_price, out_price = self.PRICING.get(self.model, (0, 0))
        return (input_tokens * in_price) + (output_tokens * out_price)

    def get_model_string(self):
        return f"Anthropic ({self.model})"


# ==========================================================
# DEEPSEEK TRANSLATOR
# ==========================================================
class DeepSeekTranslator(BaseTranslator):

    PRICING = {
        "deepseek-v4-flash": (0.00000014, 0.00000028),
    }

    def __init__(self):
        self.api_key = ADDON.getSetting('deepseek_api_key')
        self.temperature = self._get_temperature("DeepSeek")

        model_map = {
            "DeepSeek V4 Flash": "deepseek-v4-flash",
        }

        self.model = model_map.get(
            ADDON.getSetting('deepseek_model'),
            "deepseek-v4-flash"
        )

    def translate_batch(self, text_list, expected_count, context_list=None):

        if not self.api_key:
            log("DeepSeek API key missing")
            return None, 0, 0

        from languages import get_lang_params, get_active_language_setting
        src_name, _ = get_lang_params(get_active_language_setting(ADDON, "DeepSeek", 'source'))
        trg_name, _ = get_lang_params(get_active_language_setting(ADDON, "DeepSeek", 'target'))

        if src_name.lower() != "auto-detect":
            lang_instruction = f"Translate from {src_name} to {trg_name}."
        else:
            lang_instruction = f"Detect the source language and translate to {trg_name}."

        prefixed = [f"L{i:03}: {t}" for i, t in enumerate(text_list)]
        input_text = build_source_context_block(context_list) + "\n".join(prefixed)

        style_block = build_style_instruction(trg_name)
        localization_block = build_localization_instruction()

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a professional subtitle localizer.\n"
                        f"{lang_instruction}\n\n"
                        "STRICT RULES (MANDATORY):\n"
                        "1. Preserve 'Lxxx:' anchors EXACTLY.\n"
                        f"2. Return EXACTLY {expected_count} lines.\n"
                        "3. Return ONLY prefixed translated lines.\n"
                        "4. Do NOT add commentary.\n\n"
                        "5. If read-only Cxxx source context is provided, use it for meaning only and never include it in the output.\n\n"
                        f"{localization_block}\n"
                        f"{style_block}"
                    )
                },
                {"role": "user", "content": input_text}
            ],
            "temperature": self.temperature
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json"
        }

        try:
            r = requests.post(
                "https://api.deepseek.com/v1/chat/completions",
                headers=headers,
                json=payload,
                timeout=30
            )

            if r.status_code != 200:
                log(f"DeepSeek error ({self.model}): {r.status_code} | {r.text[:500]}")
                return None, 0, 0

            data = r.json()
            raw = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

            translated = self._scrub(raw, expected_count)
            if not translated:
                log("DeepSeek scrub failed")
                return None, 0, 0

            usage = data.get("usage", {})
            in_t = usage.get("prompt_tokens", 0)
            out_t = usage.get("completion_tokens", 0)

            return translated, in_t, out_t

        except Exception as e:
            log(f"DeepSeek exception ({self.model}): {e}")
            return None, 0, 0

    def calculate_cost(self, input_tokens, output_tokens):
        in_price, out_price = self.PRICING.get(self.model, (0, 0))
        return (input_tokens * in_price) + (output_tokens * out_price)

    def get_model_string(self):
        return f"DeepSeek ({self.model})"


# ==========================================================
# OPENROUTER TRANSLATOR
# ==========================================================
class OpenRouterTranslator(BaseTranslator):

    DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(self):
        self.api_key = ADDON.getSetting('openrouter_api_key')
        self.temperature = self._get_temperature("OpenRouter")

        raw_model = (ADDON.getSetting('openrouter_custom_model') or '').strip()
        self.model = raw_model if raw_model else "deepseek/deepseek-v4-flash:free"

        raw_base_url = (ADDON.getSetting('openrouter_base_url') or '').strip()
        self.base_url = raw_base_url if raw_base_url else self.DEFAULT_BASE_URL

    def _get_endpoint(self):
        return self.base_url.rstrip("/") + "/chat/completions"

    def translate_batch(self, text_list, expected_count, context_list=None):

        if not self.api_key:
            log("OpenRouter API key missing")
            return None, 0, 0

        from languages import get_lang_params, get_active_language_setting
        src_name, _ = get_lang_params(get_active_language_setting(ADDON, "OpenRouter", 'source'))
        trg_name, _ = get_lang_params(get_active_language_setting(ADDON, "OpenRouter", 'target'))

        if src_name.lower() != "auto-detect":
            lang_instruction = f"Translate from {src_name} to {trg_name}."
        else:
            lang_instruction = f"Detect the source language and translate to {trg_name}."

        prefixed = [f"L{i:03}: {t}" for i, t in enumerate(text_list)]
        input_text = build_source_context_block(context_list) + "\n".join(prefixed)

        style_block = build_style_instruction(trg_name)
        localization_block = build_localization_instruction()

        endpoint = self._get_endpoint()

        payload = {
            "model": self.model,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a professional subtitle localizer.\n"
                        f"{lang_instruction}\n\n"
                        "STRICT RULES (MANDATORY):\n"
                        "1. Preserve 'Lxxx:' anchors EXACTLY.\n"
                        f"2. Return EXACTLY {expected_count} lines.\n"
                        "3. Return ONLY prefixed translated lines.\n"
                        "4. Do NOT add commentary.\n\n"
                        "5. If read-only Cxxx source context is provided, use it for meaning only and never include it in the output.\n\n"
                        f"{localization_block}\n"
                        f"{style_block}"
                    )
                },
                {"role": "user", "content": input_text}
            ],
            "temperature": self.temperature
        }

        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            r = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=30
            )

            if r.status_code != 200:
                log(f"OpenRouter error ({self.model}): {r.status_code} | {r.text[:500]}")
                return None, 0, 0

            data = r.json()
            raw = (
                data.get("choices", [{}])[0]
                .get("message", {})
                .get("content", "")
                .strip()
            )

            translated = self._scrub(raw, expected_count)
            if not translated:
                log("OpenRouter scrub failed")
                return None, 0, 0

            usage = data.get("usage", {})
            in_t = usage.get("prompt_tokens", 0)
            out_t = usage.get("completion_tokens", 0)

            return translated, in_t, out_t

        except Exception as e:
            log(f"OpenRouter exception ({self.model}): {e}")
            return None, 0, 0

    def calculate_cost(self, input_tokens, output_tokens):
        # OpenRouter pricing varies per model; report $0 for unknown models
        return 0.0

    def get_model_string(self):
        return f"OpenRouter ({self.model})"


# ==========================================================
# DEEPL TRANSLATOR
# ==========================================================
class DeepLTranslator(BaseTranslator):

    PRICE_PER_CHARACTER = 0.0
    STATUS_MESSAGES = {
        400: "Bad request. Check source and target language settings.",
        403: "Authorization failed. Check your DeepL API key.",
        413: "Request too large for DeepL.",
        429: "Too many requests. DeepL rate limit reached.",
        456: "Quota exceeded on the DeepL account.",
        503: "DeepL service is temporarily unavailable.",
    }

    def __init__(self):
        self.api_key = ADDON.getSetting('deepl_api_key')

    def _count_submitted_characters(self, text_list):
        return sum(len(item) for item in text_list)

    def _get_lang_codes(self):
        from languages import get_lang_params, get_provider_language_code, get_active_language_setting

        source_value = get_active_language_setting(ADDON, "DeepL", 'source')
        target_value = get_active_language_setting(ADDON, "DeepL", 'target')

        src_name, _ = get_lang_params(source_value)
        trg_name, _ = get_lang_params(target_value)

        src_code = get_provider_language_code("DeepL", source_value, allow_auto_detect=True)
        trg_code = get_provider_language_code("DeepL", target_value)

        if not trg_code:
            log(f"DeepL target language not supported: {trg_name}")
            return None, None, src_name, trg_name

        return src_code, trg_code, src_name, trg_name

    def translate_batch(self, text_list, expected_count, context_list=None):

        if not self.api_key:
            log("DeepL API key missing")
            return None, 0, 0

        src_code, trg_code, src_name, trg_name = self._get_lang_codes()
        if not trg_code:
            return None, 0, 0

        if src_name.lower() != "auto-detect" and not src_code:
            log(f"DeepL source language not supported: {src_name}")
            return None, 0, 0

        prefixed = [f"L{i:03}: {t}" for i, t in enumerate(text_list)]
        submitted_characters = self._count_submitted_characters(prefixed)

        payload = {
            "text": prefixed,
            "target_lang": trg_code,
            "split_sentences": "0",
        }

        if src_code:
            payload["source_lang"] = src_code

        headers = {
            "Authorization": "DeepL-Auth-Key " + self.api_key,
            "Content-Type": "application/json",
        }

        try:
            r = requests.post(
                "https://api-free.deepl.com/v2/translate",
                headers=headers,
                json=payload,
                timeout=30
            )

            if r.status_code != 200:
                error_msg = self.STATUS_MESSAGES.get(r.status_code, r.text[:300])
                log(f"DeepL error: {r.status_code} | {error_msg}")
                return None, 0, 0

            data = r.json()
            translated = [
                item.get("text", "").strip()
                for item in data.get("translations", [])
            ]

            if len(translated) != expected_count or any(not line for line in translated):
                log("DeepL returned an unexpected number of translated lines")
                return None, 0, 0

            billed_characters = data.get("billed_characters", 0)
            try:
                billed_characters = int(billed_characters)
            except (TypeError, ValueError):
                billed_characters = 0

            if billed_characters <= 0:
                billed_characters = submitted_characters

            return translated, billed_characters, 0

        except Exception as e:
            log(f"DeepL exception: {e}")
            return None, 0, 0

    def calculate_cost(self, input_tokens, output_tokens):
        return float(input_tokens) * self.PRICE_PER_CHARACTER

    def get_model_string(self):
        return "DeepL Free"


# ==========================================================
# LIBRETRANSLATE TRANSLATOR
# ==========================================================
class LibreTranslateTranslator(BaseTranslator):

    STATUS_MESSAGES = {
        400: "Bad request. Check LibreTranslate URL and language settings.",
        403: "Authorization failed. Check your LibreTranslate API key.",
        429: "Too many requests. LibreTranslate rate limit reached.",
        500: "LibreTranslate server error.",
        503: "LibreTranslate service is temporarily unavailable.",
    }

    def __init__(self):
        self.base_url = (ADDON.getSetting('libretranslate_url') or '').strip()
        self.api_key = (ADDON.getSetting('libretranslate_api_key') or '').strip()

    def _get_endpoint(self):
        if not self.base_url:
            log("LibreTranslate URL missing")
            return None

        if not (self.base_url.startswith("http://") or self.base_url.startswith("https://")):
            log("LibreTranslate URL must start with http:// or https://")
            return None

        return self.base_url.rstrip("/") + "/translate"

    def translate_batch(self, text_list, expected_count, context_list=None):
        endpoint = self._get_endpoint()
        if not endpoint:
            return None, 0, 0

        from languages import get_lang_params, get_active_language_setting

        source_value = get_active_language_setting(ADDON, "LibreTranslate", 'source')
        target_value = get_active_language_setting(ADDON, "LibreTranslate", 'target')

        _, src_code = get_lang_params(source_value)
        _, trg_code = get_lang_params(target_value)

        prefixed = [f"L{i:03}: {t}" for i, t in enumerate(text_list)]
        payload = {
            "q": prefixed,
            "source": src_code,
            "target": trg_code,
            "format": "text",
        }

        if self.api_key:
            payload["api_key"] = self.api_key

        headers = {
            "Content-Type": "application/json",
        }

        try:
            r = requests.post(
                endpoint,
                headers=headers,
                json=payload,
                timeout=30
            )

            if r.status_code != 200:
                error_msg = self.STATUS_MESSAGES.get(r.status_code, r.text[:300])
                log(f"LibreTranslate error: {r.status_code} | {error_msg}")
                return None, 0, 0

            data = r.json()
            translated = data.get("translatedText", [])
            if isinstance(translated, str):
                translated = self._scrub(translated, expected_count)
            else:
                translated = [str(item).strip() for item in translated]

            if not translated or len(translated) != expected_count or any(not line for line in translated):
                log("LibreTranslate returned an unexpected number of translated lines")
                return None, 0, 0

            billed_characters = sum(len(item) for item in prefixed)
            return translated, billed_characters, 0

        except Exception as e:
            log(f"LibreTranslate exception: {e}")
            return None, 0, 0

    def calculate_cost(self, input_tokens, output_tokens):
        return 0.0

    def get_model_string(self):
        return "LibreTranslate"


# ==========================================================
# PUBLIC API
# ==========================================================
def _get_translator():
    provider = ADDON.getSetting('provider')
    if provider == "OpenAI":
        return OpenAITranslator()
    if provider == "Anthropic":
        return AnthropicTranslator()
    if provider == "DeepSeek":
        return DeepSeekTranslator()
    if provider == "OpenRouter":
        return OpenRouterTranslator()
    if provider == "DeepL":
        return DeepLTranslator()
    if provider == "LibreTranslate":
        return LibreTranslateTranslator()
    return GeminiTranslator()


def translate_batch(text_list, expected_count, context_list=None):
    return _get_translator().translate_batch(text_list, expected_count, context_list=context_list)


def calculate_cost(input_tokens, output_tokens):
    return _get_translator().calculate_cost(input_tokens, output_tokens)


def get_model_string():
    return _get_translator().get_model_string()
