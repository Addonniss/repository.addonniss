# -*- coding: utf-8 -*-
import xbmcgui

from . import radarr, sonarr
from .common import alert, get_addon_path, get_setting, notify, set_setting

TITLE = "KodiARR Instant"

URL_ID = 3101
API_ID = 3102
ROOT_ID = 3103
PROFILE_ID = 3104

SWITCH_ID = 3201
TEST_ID = 3202
SAVE_CLOSE_ID = 3203
CLOSE_ID = 3204


class QuickSetupDialog(xbmcgui.WindowXMLDialog):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.service_name = ""
        self.field_map = {}
        self.test_callback = None
        self.options_callback = None
        self.switch_label = ""
        self.switch_target = None
        self.test_label = ""
        self.help_text = {}
        self._switch_requested = False
        self._selected_profile_id = ""
        self._selected_profile_label = ""

    def onInit(self):
        self.getControl(3001).setLabel("{} Quick Setup".format(self.service_name))
        self.getControl(SWITCH_ID).setLabel(self.switch_label)
        self.getControl(TEST_ID).setLabel(self.test_label)
        self.getControl(URL_ID).setText(get_setting(self.field_map["url"]))
        self.getControl(API_ID).setText(get_setting(self.field_map["api"]))
        self.getControl(ROOT_ID).setText(get_setting(self.field_map["root"]))
        self._selected_profile_id = get_setting(self.field_map["profile"], "")
        self._selected_profile_label = get_setting(self.field_map["profile_label"], "")
        self.getControl(PROFILE_ID).setText(self._selected_profile_label or self._selected_profile_id or "1")
        self._set_help(URL_ID)

    def onFocus(self, control_id):
        self._set_help(control_id)

    def onClick(self, control_id):
        if control_id == SWITCH_ID:
            self._switch_requested = True
            self.close()
        elif control_id == TEST_ID:
            self._test_and_load()
        elif control_id == SAVE_CLOSE_ID:
            if self._save(show_notification=True):
                self.close()
        elif control_id == CLOSE_ID:
            self.close()

    def onAction(self, action):
        action_id = action.getId()
        if action_id in (
            xbmcgui.ACTION_NAV_BACK,
            xbmcgui.ACTION_PREVIOUS_MENU,
            xbmcgui.ACTION_PARENT_DIR,
        ):
            self.close()

    def _collect_values(self):
        return {
            self.field_map["url"]: self.getControl(URL_ID).getText().strip(),
            self.field_map["api"]: self.getControl(API_ID).getText().strip(),
            self.field_map["root"]: self.getControl(ROOT_ID).getText().strip(),
            "profile_text": self.getControl(PROFILE_ID).getText().strip(),
        }

    def _save(self, show_notification):
        values = self._collect_values()
        if not values[self.field_map["url"]] or not values[self.field_map["api"]] or not values[self.field_map["root"]]:
            notify(TITLE, "Please fill all fields", xbmcgui.NOTIFICATION_WARNING)
            return False

        profile_id, profile_label = self._resolve_profile_value(values["profile_text"])
        if not profile_id:
            notify(TITLE, "Please load or enter a valid quality profile", xbmcgui.NOTIFICATION_WARNING)
            return False

        saved_ok = True
        for key in (self.field_map["url"], self.field_map["api"], self.field_map["root"]):
            value = values[key]
            saved_ok = set_setting(key, value) and saved_ok
        saved_ok = set_setting(self.field_map["profile"], profile_id) and saved_ok
        saved_ok = set_setting(self.field_map["profile_label"], profile_label) and saved_ok

        if not saved_ok:
            notify(TITLE, "Failed to save settings", xbmcgui.NOTIFICATION_ERROR)
            return False

        if show_notification:
            notify(TITLE, "{} settings saved".format(self.service_name))
        return True

    def _set_help(self, control_id):
        text = self.help_text.get(control_id, self.help_text.get("default", ""))
        self.getControl(3002).setText(text)

    def _save_connection_fields(self):
        url = self.getControl(URL_ID).getText().strip()
        api = self.getControl(API_ID).getText().strip()

        if not url or not api:
            notify(TITLE, "Please fill {} URL and API key".format(self.service_name), xbmcgui.NOTIFICATION_WARNING)
            return None

        if not (set_setting(self.field_map["url"], url) and set_setting(self.field_map["api"], api)):
            notify(TITLE, "Failed to save connection fields", xbmcgui.NOTIFICATION_ERROR)
            return None

        return {"url": url, "api": api}

    def _resolve_profile_value(self, profile_text):
        current_text = (profile_text or "").strip()
        stored_id = get_setting(self.field_map["profile"], "")
        stored_label = get_setting(self.field_map["profile_label"], "")

        if self._selected_profile_id and current_text == self._selected_profile_label:
            return self._selected_profile_id, self._selected_profile_label
        if stored_id and stored_label and current_text == stored_label:
            return stored_id, stored_label
        if current_text.isdigit():
            return current_text, ""
        if stored_id and current_text == stored_id:
            return stored_id, stored_label
        return "", ""

    def _test_and_load(self):
        connection = self._save_connection_fields()
        if not connection:
            return

        if not self.test_callback(show_notification=True, **connection):
            return

        try:
            options = self.options_callback(**connection)
        except Exception as error:
            alert(TITLE, "Failed to load instance data:\n{}".format(error))
            return

        root = self._choose_root(options.get("roots", []))
        if not root:
            return

        profile_id, profile_label = self._choose_profile(options.get("profiles", []))
        if not profile_id:
            return

        self.getControl(ROOT_ID).setText(root)
        self.getControl(PROFILE_ID).setText(profile_label)
        self._selected_profile_id = str(profile_id)
        self._selected_profile_label = profile_label

        set_setting(self.field_map["root"], root)
        set_setting(self.field_map["profile"], self._selected_profile_id)
        set_setting(self.field_map["profile_label"], self._selected_profile_label)
        notify(TITLE, "{} folders and profiles loaded".format(self.service_name))

    def _choose_root(self, roots):
        roots = [item for item in roots if item]
        if not roots:
            notify(TITLE, "No root folders found in {}".format(self.service_name), xbmcgui.NOTIFICATION_WARNING)
            return ""

        current_root = self.getControl(ROOT_ID).getText().strip()
        if len(roots) == 1:
            return roots[0]

        preselect = roots.index(current_root) if current_root in roots else 0
        choice = xbmcgui.Dialog().select("{} Root Folder".format(self.service_name), roots, preselect=preselect)
        return roots[choice] if choice >= 0 else ""

    def _choose_profile(self, profiles):
        profiles = [item for item in profiles if item.get("id") is not None and item.get("name")]
        if not profiles:
            notify(TITLE, "No quality profiles found in {}".format(self.service_name), xbmcgui.NOTIFICATION_WARNING)
            return "", ""

        current_profile_id = self._selected_profile_id or get_setting(self.field_map["profile"], "")
        if len(profiles) == 1:
            profile = profiles[0]
            return str(profile["id"]), profile["name"]

        labels = [item["name"] for item in profiles]
        preselect = 0
        for index, item in enumerate(profiles):
            if str(item["id"]) == str(current_profile_id):
                preselect = index
                break
        choice = xbmcgui.Dialog().select("{} Quality Profile".format(self.service_name), labels, preselect=preselect)
        if choice < 0:
            return "", ""
        profile = profiles[choice]
        return str(profile["id"]), profile["name"]


def _run_dialog(service_name, field_map, test_callback, options_callback, switch_label, switch_target, test_label, help_text):
    dialog = QuickSetupDialog("QuickSetupDialog.xml", get_addon_path(), "default", "1080i")
    dialog.service_name = service_name
    dialog.field_map = field_map
    dialog.test_callback = test_callback
    dialog.options_callback = options_callback
    dialog.switch_label = switch_label
    dialog.switch_target = switch_target
    dialog.test_label = test_label
    dialog.help_text = help_text
    dialog.doModal()
    next_dialog = dialog.switch_target if dialog._switch_requested else None
    del dialog

    if next_dialog:
        next_dialog()


def _run_radarr_flow():
    _run_dialog(
        "Radarr",
        {
            "url": "radarr_url",
            "api": "radarr_api",
            "root": "radarr_root",
            "profile": "radarr_quality_profile",
            "profile_label": "radarr_quality_profile_label",
        },
        radarr.test_connection,
        radarr.fetch_setup_options,
        "Open Sonarr Settings",
        _run_sonarr_flow,
        "Test & Load",
        {
            "default": "Move through the form and the helper text will follow the selected field or action.",
            URL_ID: "Base address of your Radarr instance, for example http://192.168.1.10:7878",
            API_ID: "API key from Radarr Settings > General.",
            ROOT_ID: "Root folder path Radarr should use when adding new movies. Test & Load can auto-fill or let you choose it.",
            PROFILE_ID: "Quality profile loaded from Radarr by name. The add-on stores the matching profile ID automatically.",
            SWITCH_ID: "Open the Sonarr custom settings page without going back to the launcher.",
            TEST_ID: "Save the current Radarr URL and API key, test the connection, then load root folders and quality profiles from Radarr.",
            SAVE_CLOSE_ID: "Save the current Radarr values and close this page.",
            CLOSE_ID: "Close this page without saving any new changes.",
        },
    )


def _run_sonarr_flow():
    _run_dialog(
        "Sonarr",
        {
            "url": "sonarr_url",
            "api": "sonarr_api",
            "root": "sonarr_root",
            "profile": "sonarr_quality_profile",
            "profile_label": "sonarr_quality_profile_label",
        },
        sonarr.test_connection,
        sonarr.fetch_setup_options,
        "Open Radarr Settings",
        _run_radarr_flow,
        "Test & Load",
        {
            "default": "Move through the form and the helper text will follow the selected field or action.",
            URL_ID: "Base address of your Sonarr instance, for example http://192.168.1.11:8989",
            API_ID: "API key from Sonarr Settings > General.",
            ROOT_ID: "Root folder path Sonarr should use when adding new series. Test & Load can auto-fill or let you choose it.",
            PROFILE_ID: "Quality profile loaded from Sonarr by name. The add-on stores the matching profile ID automatically.",
            SWITCH_ID: "Open the Radarr custom settings page without going back to the launcher.",
            TEST_ID: "Save the current Sonarr URL and API key, test the connection, then load root folders and quality profiles from Sonarr.",
            SAVE_CLOSE_ID: "Save the current Sonarr values and close this page.",
            CLOSE_ID: "Close this page without saving any new changes.",
        },
    )


def open_radarr_settings():
    _run_radarr_flow()


def open_sonarr_settings():
    _run_sonarr_flow()


def show_launcher_menu():
    options = [
        "Radarr Settings",
        "Sonarr Settings",
    ]
    choice = xbmcgui.Dialog().select(TITLE, options)

    if choice == 0:
        _run_radarr_flow()
    elif choice == 1:
        _run_sonarr_flow()
