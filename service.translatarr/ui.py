# -*- coding: utf-8 -*-
import xbmcgui
import xbmcaddon
import time

ADDON = xbmcaddon.Addon('service.translatarr')
DIALOG = xbmcgui.Dialog()


# -----------------------------------
# Notifications
# -----------------------------------
def notify(msg, title="Translatarr", duration=3000):
    """Display a simple notification."""
    DIALOG.notification(title, msg, xbmcgui.NOTIFICATION_INFO, duration)


# -----------------------------------
# Helper: Format Time
# -----------------------------------
def format_time(seconds):
    """Convert seconds to human-readable H:M:S format."""
    seconds = int(seconds)
    mins, secs = divmod(seconds, 60)
    hrs, mins = divmod(mins, 60)

    if hrs > 0:
        return f"{hrs}h {mins}m {secs}s"
    if mins > 0:
        return f"{mins}m {secs}s"
    return f"{secs}s"


# -----------------------------------
# Statistics Popup
# -----------------------------------
def show_stats_box(src_file, trg_file, trg_name, save_path,
                   cost, tokens, chunks, chunk_size,
                   model_name, total_time):
    """
    Display statistics popup with translation details.
    """
    try:
        show_statistics = ADDON.getSettingBool("show_stats")
    except:
        show_statistics = True

    if not show_statistics:
        return

    if "gemini" in model_name.lower():
        model_color = "mediumpurple"
        provider_badge = "[Gemini]"
        usage_label = "Total Tokens"
    elif "deepl" in model_name.lower():
        model_color = "darkorange"
        provider_badge = "[DeepL]"
        usage_label = "Total Characters"
    elif "libretranslate" in model_name.lower():
        model_color = "limegreen"
        provider_badge = "[LibreTranslate]"
        usage_label = "Total Characters"
    else:
        model_color = "deepskyblue"
        provider_badge = "[OpenAI]"
        usage_label = "Total Tokens"

    stats_msg = (
        "[B][COLOR gold]TRANSLATARR SUCCESS[/COLOR][/B]\n"
        "------------------------------------------------------------\n"
        f"[B]Provider:[/B] {provider_badge}\n"
        f"[B]Source:[/B] {src_file}\n"
        f"[B]Target:[/B] {trg_file}\n"
        f"[B]Saved To:[/B] {save_path}\n"
        f"[B]Language:[/B] {trg_name}\n"
        f"[B]Model:[/B]  [COLOR {model_color}]{model_name}[/COLOR]\n"
        f"[B]Time:[/B] {format_time(total_time)}\n\n"
        "[B]USAGE DETAILS[/B]\n"
        "------------------------------------------------------------\n"
        f"• {usage_label}:   {tokens:,}\n"
        f"• Total Chunks:   {chunks} (Size: {chunk_size})\n"
        f"• Estimated Cost: ${cost:.4f}"
    )

    DIALOG.textviewer("Translatarr Statistics", stats_msg, usemono=False)


# -----------------------------------
# Progress Handler (Milestone + ETA)
# -----------------------------------
class TranslationProgress:
    def __init__(self, model_name="", title="Translatarr"):
        try:
            self.use_notifications = ADDON.getSettingBool("notify_mode")
        except:
            self.use_notifications = True

        self.title = title
        self.model_name = model_name.lower()

        # Provider badge
        if "gemini" in self.model_name:
            self.provider = "Gemini"
        elif "deepl" in self.model_name:
            self.provider = "DeepL"
        elif "libretranslate" in self.model_name:
            self.provider = "LibreTranslate"
        elif "openai" in self.model_name or "gpt" in self.model_name:
            self.provider = "OpenAI"
        else:
            self.provider = "AI"

        # Timing
        self.start_time = time.time()

        # Milestones
        self.milestones = {5, 15, 35, 60, 85}
        self.triggered = set()

        self.pDialog = None

        if not self.use_notifications:
            self.pDialog = xbmcgui.DialogProgress()
            self.pDialog.create(title, "Initializing...")
        else:
            notify(f"[{self.provider}] Translation Started...", title=self.title)

    def update(self, percent, src_name, trg_name,
               chunk_num, total_chunks,
               lines_done, total_lines):
        """Update the progress dialog or milestone notifications."""
        percent = int(percent)
        elapsed = time.time() - self.start_time

        # Estimate remaining time
        if percent > 0:
            estimated_total = elapsed / (percent / 100.0)
            remaining = estimated_total - elapsed
            eta = format_time(remaining)
        else:
            eta = "Calculating..."

        # -----------------------------------
        # Notification Mode
        # -----------------------------------
        if self.use_notifications:
            for milestone in sorted(self.milestones):
                if percent >= milestone and milestone not in self.triggered:
                    notify(
                        f"[{self.provider}] {milestone}% • ETA {eta}",
                        title=self.title,
                        duration=3000
                    )
                    self.triggered.add(milestone)
            return

        # -----------------------------------
        # Dialog Mode
        # -----------------------------------
        if self.pDialog:
            line1 = f"Provider: {self.provider}"
            line2 = f"Chunk {chunk_num}/{total_chunks}"
            line3 = f"{lines_done:,}/{total_lines:,} lines"
            line4 = f"{percent}% complete"
            line5 = f"ETA: {eta}"

            self.pDialog.update(
                percent,
                f"{line1}\n{line2}\n{line3}\n{line4}\n{line5}"
            )

    def is_canceled(self):
        """Check if the user canceled the dialog."""
        if self.use_notifications or self.pDialog is None:
            return False
        return self.pDialog.iscanceled()

    def close(self):
        """Close the progress dialog or show final notification."""
        total_time = format_time(time.time() - self.start_time)

        if self.use_notifications:
            notify(
                f"[{self.provider}] Completed in {total_time}",
                title=self.title,
                duration=4000
            )

        if self.pDialog:
            self.pDialog.close()
            self.pDialog = None
