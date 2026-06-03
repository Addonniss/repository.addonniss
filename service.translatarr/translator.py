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
        )

    # Default = Family-Friendly
    return (
        "STYLE REQUIREMENT:\n"
        f"- Tone: clean, neutral, broadcast-safe {trg_name}.\n"
        "- Avoid profanity.\n"
        "- Replace strong insults with mild alternatives.\n"
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
        "gemini-3.5-flash": (0.0000015, 0.0000090),
        "gemini-3.1-flash-lite": (0.00000025, 0.0000015),
        "gemini-2.5-pro": (0.00000125, 0.0000100),
        "gemini-2.5-flash": (0.0000003, 0.0000025),
        "gemini-2.5-flash-lite": (0.0000001, 0.0000004),
    }

    def __init__(self):
        self.api_key = ADDON.getSetting('api_key')
        self.temperature = self._get_temperature("Gemini")
        self.fast_mode = False

        model_map = {
            "Gemini 3.5 Flash": "gemini-3.5-flash",
            "Gemini 3.1 Flash-Lite": "gemini-3.1-flash-lite",
            "Fast Mode - Gemini 3.1 Flash-Lite": "gemini-3.1-flash-lite",
            "Gemini 2.5 Pro": "gemini-2.5-pro",
            "Gemini 2.5 Flash": "gemini-2.5-flash",
            "Fast Mode - Gemini 2.5 Flash": "gemini-2.5-flash",
            "Gemini 2.5 Flash-Lite": "gemini-2.5-flash-lite"
        }

        selected_model = ADDON.getSetting('model')
        self.model = model_map.get(selected_model, "gemini-2.5-flash")
        self.fast_mode = selected_model in (
            "Fast Mode - Gemini 2.5 Flash",
            "Fast Mode - Gemini 3.1 Flash-Lite",
        )

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
                        "1. Translate strictly line-by-line.\n"
                        "2. Preserve 'Lxxx:' anchors EXACTLY.\n"
                        f"3. Return EXACTLY {expected_count} lines.\n"
                        "4. Return ONLY prefixed translated lines.\n"
                        "5. Do NOT add commentary.\n\n"
                        "6. If read-only Cxxx source context is provided, use it for meaning only and never include it in the output.\n\n"
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

        if self.fast_mode and self.model in ("gemini-2.5-flash", "gemini-3.1-flash-lite"):
            payload["generationConfig"]["thinkingConfig"] = {
                "thinkingBudget": 0
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
        suffix = " Fast" if self.fast_mode else ""
        return f"Gemini ({self.model}{suffix})"


# ==========================================================
# OPENAI TRANSLATOR
# ==========================================================
class OpenAITranslator(BaseTranslator):

    PRICING = {
        "gpt-4o-mini": (0.00000015, 0.00000060),
        "gpt-4o": (0.0000025, 0.0000100),
        "gpt-5-mini": (0.00000025, 0.0000020),
    }

    def __init__(self):
        self.api_key = ADDON.getSetting('openai_api_key')
        self.temperature = self._get_temperature("OpenAI")

        model_map = {
            "gpt-4o-mini": "gpt-4o-mini",
            "gpt-4o": "gpt-4o",
            "gpt-5-mini": "gpt-5-mini"
        }

        self.model = model_map.get(ADDON.getSetting('openai_model'), "gpt-4o-mini")

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
                        "1. Translate strictly line-by-line.\n"
                        "2. Preserve 'Lxxx:' anchors EXACTLY.\n"
                        f"3. Return EXACTLY {expected_count} lines.\n"
                        "4. Return ONLY prefixed translated lines.\n"
                        "5. Do NOT add commentary.\n\n"
                        "6. If read-only Cxxx source context is provided, use it for meaning only and never include it in the output.\n\n"
                        f"{localization_block}\n"
                        f"{style_block}"
                    )
                },
                {"role": "user", "content": input_text}
            ]
        }
        if self._supports_custom_temperature():
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
        return f"OpenAI ({self.model})"


# ==========================================================
# ANTHROPIC TRANSLATOR
# ==========================================================
class AnthropicTranslator(BaseTranslator):

    PRICING = {
        "claude-haiku-4-5": (0.0000010, 0.0000050),
        "claude-sonnet-4-6": (0.0000030, 0.0000150),
        "claude-opus-4-7": (0.0000050, 0.0000250),
    }

    def __init__(self):
        self.api_key = ADDON.getSetting('anthropic_api_key')
        self.temperature = self._get_temperature("Anthropic")

        model_map = {
            "Claude Haiku": "claude-haiku-4-5",
            "Claude Sonnet": "claude-sonnet-4-6",
            "Claude Opus": "claude-opus-4-7",
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
                "1. Translate strictly line-by-line.\n"
                "2. Preserve 'Lxxx:' anchors EXACTLY.\n"
                f"3. Return EXACTLY {expected_count} lines.\n"
                "4. Return ONLY prefixed translated lines.\n"
                "5. Do NOT add commentary.\n\n"
                "6. If read-only Cxxx source context is provided, use it for meaning only and never include it in the output.\n\n"
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
        "deepseek-chat": (0.00000027, 0.00000110),       # V4 Pro
        "deepseek-chat-flash": (0.00000014, 0.00000055),  # V4 Flash
    }

    def __init__(self):
        self.api_key = ADDON.getSetting('deepseek_api_key')
        self.temperature = self._get_temperature("DeepSeek")

        model_map = {
            "DeepSeek V4 Pro": "deepseek-chat",
            "DeepSeek V4 Flash": "deepseek-chat-flash",
        }

        self.model = model_map.get(
            ADDON.getSetting('deepseek_model'),
            "deepseek-chat"
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
                        "1. Translate strictly line-by-line.\n"
                        "2. Preserve 'Lxxx:' anchors EXACTLY.\n"
                        f"3. Return EXACTLY {expected_count} lines.\n"
                        "4. Return ONLY prefixed translated lines.\n"
                        "5. Do NOT add commentary.\n\n"
                        "6. If read-only Cxxx source context is provided, use it for meaning only and never include it in the output.\n\n"
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
