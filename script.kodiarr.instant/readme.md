# 🎬 KodiARR Instant

**KodiARR Instant** allows you to instantly send movies and TV shows from Kodi to **Radarr** or **Sonarr** for automated downloading. It adds a seamless contextual menu inside Kodi, letting you push content directly to your media automation stack with a single click.

---

## ✨ Features

* 🚀 **Add Movies to Radarr** – Send film titles directly to your movie manager.
* 📺 **Add TV Shows to Sonarr** – Support for entire shows, specific seasons, or single episodes.
* 🔍 **Automatic Metadata Detection** – Integrated support for **TMDB**, **TVDB**, and **IMDB**.
* 💡 **Smart Context Menu**:
    * *Movies* → Add to Radarr
    * *Shows / Seasons / Episodes* → Add to Sonarr
* 🌐 **Universal Compatibility**:
    * Kodi Library
    * TMDB Helper
    * Custom Widgets & Skins
    * Streaming Add-ons
* 🛠️ **Built-in Test & Load** – Verify your Radarr and Sonarr settings and load root folders plus quality profiles directly from the instance.
* 🪶 **Lightweight** – Minimal dependencies for a fast experience.

---

## 📥 Installation

### 1. Install Repository
1. Open **Kodi**.
2. Go to **Settings** ⚙️ → **File Manager**.
3. Click **Add Source**.
4. Enter the URL: `https://addonniss.github.io/repository.addonniss/`
5. Name it: `Addonniss`
6. Go to **Add-ons** → **Install from Zip**.
7. Select the **Addonniss** source and install `repository.addonniss`.

### 2. Install KodiARR Instant
1. Go to **Install from Repository**.
2. Open **Addonniss Repository**.
3. Select **Program Add-ons**.
4. Install **KodiARR Instant**.

---

## ⚙️ Setup

Open the add-on and choose **Radarr Settings** or **Sonarr Settings** to configure your connection in the custom setup window:

| Service | Required Settings |
| :--- | :--- |
| **Radarr** 🎬 | URL, API Key |
| **Sonarr** 📺 | URL, API Key |

> [!TIP]
> Use **Test & Load** to verify the connection, fetch root folders from the instance, and choose quality profiles by name.

### What Test & Load does
1. Saves the current URL and API key
2. Tests the connection to Radarr or Sonarr
3. Loads available root folders from the instance
4. Loads available quality profiles from the instance
5. Auto-fills the root folder if only one exists, or asks you to choose when multiple are available

> [!NOTE]
> The addon stores the selected quality profile using the real numeric profile ID, even though you choose it by profile name in the custom window.

---

## 🖱️ Usage

### **Movies**
* **Right-click** (or long-press) on a movie in Kodi.
* Select **Add to Radarr**.
* The movie will be added and a search will trigger immediately.

### **TV Shows**
* **Right-click** on a Show, Season, or Episode.
* Select **Add to Sonarr**.
* Sonarr will add the series and trigger the appropriate search.

---

## 🔌 Requirements & Compatibility

### **Works With**
* ✅ Kodi 20 (Nexus)
* ✅ Kodi 21 (Omega)
* ✅ Kodi 22 (ALPHA 3)
* ✅ Windows, Android / Android TV, Linux, CoreELEC / LibreELEC

### **Dependencies**
* Radarr / Sonarr instance
* Kodi
* `script.module.requests`

---

## 🛠️ Troubleshooting

If the context menu does not trigger an action:
1. **Enable Debug Logging** in Kodi settings.
2. Check the Kodi log file: `.kodi/temp/kodi.log`
3. **Verify Credentials:** Double-check your API key and rerun **Test & Load** to refresh root folders and quality profiles from Radarr/Sonarr.

---

## 🔗 Project Links

* **GitHub Repository:** [Addonniss Repository](https://github.com/Addonniss/repository.addonniss)
* **License:** MIT License
* **Credits:** Developed by **Addonniss**. Inspired by the Kodi community and the ARR ecosystem.
