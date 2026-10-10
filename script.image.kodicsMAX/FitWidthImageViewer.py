import xbmc
import xbmcgui
import xbmcvfs
import xbmcaddon
import platform
import os
import sys
import zipfile
import time
import traceback
import subprocess
# Add lib folder to path so rarfile can be imported
#addon_dir = xbmcaddon.Addon().getAddonInfo('path')
# Use the passed addon path, or fallback to explicit addon ID
if len(sys.argv) > 1:
    addon_dir = sys.argv[1]
else:
    addon_dir = xbmcvfs.translatePath(xbmcaddon.Addon('script.image.kodicsMAX').getAddonInfo('path'))

lib_path = os.path.join(addon_dir, 'lib')

if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

from lib.comic_library import ReadTracker

import uuid
import rarfile
import tempfile
import shutil
import json
from io import BytesIO
import threading
from PIL import Image
from collections import OrderedDict

from xbmcgui import (
    ACTION_MOVE_UP, ACTION_MOVE_DOWN, ACTION_MOVE_LEFT, ACTION_MOVE_RIGHT,
    ACTION_PAGE_UP, ACTION_PAGE_DOWN, ACTION_NEXT_ITEM, ACTION_PREV_ITEM,
    ACTION_NAV_BACK, ACTION_PREVIOUS_MENU, ACTION_SELECT_ITEM, ACTION_MOUSE_LEFT_CLICK, ACTION_MOUSE_RIGHT_CLICK,
    ACTION_MOUSE_WHEEL_UP, ACTION_MOUSE_WHEEL_DOWN, ACTION_MOUSE_MIDDLE_CLICK
)

#Module level helpers for android/ios/tvos
ADDON_ID = "script.image.kodicsMAX"


def _translate_special_path(path):
    try:
        return xbmcvfs.translatePath(path)
    except AttributeError:
        # Compatibility with older Kodi versions.
        return xbmc.translatePath(path)


def _is_sandboxed_platform():
    return any(
        xbmc.getCondVisibility(condition)
        for condition in (
            "System.Platform.Android",
            "System.Platform.IOS",
            "System.Platform.TVOS",
        )
    )


def _get_addon_temp_dir(workflow):
    addon = xbmcaddon.Addon(ADDON_ID)
    profile = addon.getAddonInfo("profile").rstrip("/\\")
    special_path = profile + "/temp/" + workflow
    path = _translate_special_path(special_path)

    os.makedirs(path, exist_ok=True)

    # Log and verify the translated directory is writable.
    xbmc.log(
        "KodicsMAX: temp directory for {}: {}".format(workflow, path),
        xbmc.LOGINFO,
    )
    probe_path = os.path.join(path, ".write_test_" + uuid.uuid4().hex)
    try:
        with open(probe_path, "wb") as probe:
            probe.write(b"ok")
    except Exception:
        xbmc.log(
            "KodicsMAX: cannot write to temp directory {}:\n{}".format(
                path, traceback.format_exc()
            ),
            xbmc.LOGERROR,
        )
        raise
    finally:
        try:
            if os.path.exists(probe_path):
                os.remove(probe_path)
        except OSError:
            pass

    return path


class SettingsManager:
    """Handles loading, saving, and displaying settings from settings.json"""
    DEFAULT_SETTINGS = {
        'mute_audio': True,
        'scroll_distance': 100,
        'zoom_level': 100
    }


    def __init__(self, addon_profile):
        if addon_profile.startswith("special://"):
            try:
                addon_profile = xbmcvfs.translatePath(addon_profile)
            except AttributeError:
                addon_profile = xbmc.translatePath(addon_profile)

        self.addon_profile = addon_profile
        os.makedirs(self.addon_profile, exist_ok=True)
        self.settings_file = os.path.join(addon_profile, 'reader_settings.json')
        self.settings = self._load_settings()
        self.viewer_instance = None
    
    def _load_settings(self):
        """Load settings from JSON file."""
        settings = self.DEFAULT_SETTINGS.copy()
        xbmc.log(
        f"Loading reader settings from: {self.settings_file}",
        xbmc.LOGINFO
        )

        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r', encoding='utf-8') as f:
                    loaded = json.load(f)
                settings.update(loaded)
                xbmc.log(
                f"Loaded reader settings: {settings}",
                xbmc.LOGINFO
                )

            except Exception as e:
                xbmc.log(f"Error loading reader settings: {e}", xbmc.LOGERROR)
        return settings
    
    def _save_settings(self):
        """Save settings to JSON file."""
        try:
            os.makedirs(self.addon_profile, exist_ok=True)

            with open(self.settings_file, 'w', encoding='utf-8') as f:
                json.dump(self.settings, f, indent=2)

            xbmc.log(
            f"Saved reader settings to {self.settings_file}: "
            f"{self.settings}",
            xbmc.LOGINFO
            )
        except Exception as e:
            xbmc.log(f"Error saving reader settings to {self.settings_file}: {e}", xbmc.LOGERROR)
    
    def get_setting(self, key, default=None):
        """Get a setting value."""
        return self.settings.get(key, default)
    
    def set_setting(self, key, value):
        """Set a setting value and save."""
        self.settings[key] = value
        self._save_settings()
    
    def show_menu(self):
        """Display an interactive settings menu"""
        
        while True:
            dialog = xbmcgui.Dialog()  # Create fresh dialog each iteration
            
            items = [
                f"Mute Audio: {'ON' if self.settings['mute_audio'] else 'OFF'}",
                f"Scroll Distance: {self.settings['scroll_distance']} px",
                f"Zoom Level: {self.settings['zoom_level']}%", 
                "Close Menu",
                "Close Content"
            ]
            
            selection = dialog.select("KodicsMAX Settings", items)
            
            if selection == -1 or selection == 3:  # Close Menu (index 3) or ESC
                break
            elif selection == 0:  # Toggle Mute Audio
                value = not self.settings['mute_audio']
                self.set_setting('mute_audio', value)
                if self.viewer_instance and hasattr(self.viewer_instance, 'on_setting_changed'):
                    self.viewer_instance.on_setting_changed('mute_audio', self.settings['mute_audio'])
            elif selection == 1:  # Change Scroll Distance
                scroll_options = ['25 px', '50 px', '75 px', '100 px', '150 px', '300 px', '600 px', '1000 px']
                scroll_values = [25, 50, 75, 100, 150, 300, 600, 1000]
                current_idx = (scroll_values.index(self.settings['scroll_distance']) if self.settings['scroll_distance'] in scroll_values else 3)
                
                sel = dialog.select("Scroll Distance", scroll_options, preselect=current_idx)
                if sel != -1:
                    value = scroll_values[sel]
                    self.set_setting('scroll_distance', value)
                    if self.viewer_instance and hasattr(self.viewer_instance, 'on_setting_changed'):
                        self.viewer_instance.on_setting_changed('scroll_distance', value)
            elif selection == 2:  # Change Zoom Level
                zoom_options = ['100%', '95%', '90%', '70%', '60%', '50%', '40%', '105%', '110%', '115%', '120%']
                zoom_values = [100, 95, 90, 70, 60, 50, 40, 105, 110, 115, 120]
                current_idx = (zoom_values.index(self.settings['zoom_level']) if self.settings['zoom_level'] in zoom_values else 0)
            
                sel = dialog.select("Zoom Level", zoom_options, preselect=current_idx)
                if sel != -1:
                    value = zoom_values[sel]
                    self.set_setting('zoom_level', value)
                    if self.viewer_instance and hasattr(self.viewer_instance, 'on_setting_changed'):
                        self.viewer_instance.on_setting_changed('zoom_level', value)
            elif selection == 4:  # Close Content
                home_window = xbmcgui.Window(10000)
                #home_window.setProperty('fitwidth_done', 'true')
                return True




class VolumeManager:
   
  
    def __init__(self, settings_manager):
        self.original_volume = None
        self.changed = False
        self.settings_manager = settings_manager

    def is_audio_playing(self):
        return xbmc.Player().isPlayingAudio()

    def get_volume(self):
        query = {
            "jsonrpc": "2.0",
            "method": "Application.GetProperties",
            "params": {"properties": ["volume"]},
            "id": 1
        }
        result = xbmc.executeJSONRPC(json.dumps(query))
        return json.loads(result).get("result", {}).get("volume")

    def set_volume(self, value):
        query = {
            "jsonrpc": "2.0",
            "method": "Application.SetVolume",
            "params": {"volume": value},
            "id": 1
        }
        xbmc.executeJSONRPC(json.dumps(query))

    def maybe_mute_volume(self):
        mute_audio = self.settings_manager.get_setting('mute_audio', True)
        
        if not mute_audio:
            return
        
        # If we should mute and haven't already muted, do it now
        if not self.changed:
            self.original_volume = self.get_volume()
            self.set_volume(0)
            self.changed = True
        

    def maybe_restore_volume(self):
        if self.changed and self.original_volume is not None:
            self.set_volume(self.original_volume)
            self.changed = False

    def apply_mute_setting(self):
        """Apply the current mute_audio setting to volume."""
        mute_audio = self.settings_manager.get_setting('mute_audio', True)
        
        current_volume = self.get_volume()
        
        if mute_audio:
            # Mute: save original volume and set to 0
            if current_volume != 0:
                self.original_volume = current_volume
                self.set_volume(0)
                self.changed = True
        else:
            # Unmute: restore original volume
            if self.changed and self.original_volume is not None:
                self.set_volume(self.original_volume)
                self.changed = False

class FitWidthImageViewer(xbmcgui.Window):
    def __init__(self):
        super().__init__()
        self.settings_manager = None  # Will be set by main entrypoint
        self.startup_comic_path = None
        self.zoom_level = 100 
        self.setProperty('mouse.enabled', 'true')
        self.screen_width = self.getWidth()
        self.screen_height = self.getHeight()
        self.image_control = xbmcgui.ControlImage(
            0, 0, self.screen_width, self.screen_height, "", aspectRatio=1
        )
        #self.image_control.setVisible(True)
        #self.image_control.setEnableMouseOver(False)  # Prevent mouse focus on this control
        self.addControl(self.image_control)
        #self.setFocus(self)
        self.overlay_remove_time = None
        #xbmc.log("[kodics] FitWidthImageViewer initialized with mouse.enabled=true", xbmc.LOGINFO)
        self.action_log = {}

        #Pass page info to library
        self.current_comic_path = None
        self.read_tracker = None


        self.image_list = []
        self.current_image_index = 0
        self.offset_y = 0
        self.max_offset_y = 0
        self.running = True
        #for new cache
        self.temp_dir = None
        self._session_dir_owned = False
        self._raw_dir = None
        self._scaled_dir = None

        # Archive pages are stored as (member name, ordinal) tuples in image_list.
        self._archive_type = None
        self._raw_cache = OrderedDict()  # page index -> extracted file
        self._raw_cache_limit = 5
        self._raw_cond = threading.Condition(threading.RLock())
        self._raw_inflight = set()
        self._raw_pins = {}

        # Scaled cache is separate from the raw archive-page cache.
        self.scaled_cache = OrderedDict()
        self.cache_size = 5
        self.cache_lock = threading.RLock()
        self._scaled_cond = threading.Condition(self.cache_lock)
        self._scaled_inflight = set()
        self.temp_scaled_files = set()
        self._displayed_scaled_path = None

        self._prefetch_inflight = set()
        self._stopping = False
        self._workers = set()
        self._workers_lock = threading.Lock()

        self._request_id = 0
        self._ready_request_id = None
        self._worker_error = None
        self._worker_error_lock = threading.Lock()

        # Keep the existing image-loading fields.
        self.image_pending = False
        self.image_ready_path = None
        self.image_ready_height = None
        self.image_requested_index = None
        self.image_requested_offset_y = None
        self.image_ready_scaled_width = None
        self.lock = threading.Lock()




       
        # For threading/image loading
 
        
        self.last_height = self.screen_height
        # Overlay controls
        self.overlay_bg = None
        self.overlay_label = None
        self._show_overlay_next_update = False
        self.overlay_show_time = None
        self.image_ready_scaled_width = None


    def on_setting_changed(self, setting_name, new_value):
        """Called when a setting changes in the menu"""
        if setting_name == 'zoom_level':
            self.on_zoom_changed(new_value)
        elif setting_name == 'scroll_distance':
            self.scroll_distance = new_value
        elif setting_name == 'mute_audio':
            pass  # Handle if needed

        
    
    def display_image(self, image_path, offset_y=0):
        with self.lock:
            self._request_id += 1
            request_id = self._request_id
            page_index = self.current_image_index
            self.image_pending = True
            self.image_requested_index = page_index
            self.image_requested_offset_y = offset_y

        self._start_worker(
            self.load_and_scale_image,
            (image_path, page_index, offset_y, request_id),
            name="kodics-display",
        )


    #New
    def _prefetch_page(self, page_index):
        try:
            self.get_or_scale_image(self.image_list[page_index], page_index)
        except Exception as exc:
            xbmc.log(f"[kodics] Prefetch failed for page {page_index}: {exc}",
                     xbmc.LOGWARNING)
        finally:
            with self._raw_cond:
                self._prefetch_inflight.discard(page_index)
                self._raw_cond.notify_all()

    def preload_adjacent_images(self):
        current = self.current_image_index
        indices = [
            idx for idx in (current - 1, current + 1, current + 2)
            if 0 <= idx < len(self.image_list)
        ]

        for idx in indices:
            with self._raw_cond:
                if idx in self._prefetch_inflight:
                    continue
                if self._archive_type and idx in self._raw_cache:
                    continue
                self._prefetch_inflight.add(idx)

            if not self._start_worker(
                self._prefetch_page, (idx,), name="kodics-prefetch"
            ):
                with self._raw_cond:
                    self._prefetch_inflight.discard(idx)




    def load_and_scale_image(self, image_path, page_index, offset_y, request_id):
        try:
            _, height, width, scaled_path = self.get_or_scale_image(
                image_path, page_index
            )
        except Exception as exc:
            # Worker records the error; the dialog is shown by run() on the GUI thread.
            with self._worker_error_lock:
                self._worker_error = f"Unable to display image: {exc}"

            self._ensure_session_dir()
            scaled_path = os.path.join(
                self._scaled_dir, f"error_{uuid.uuid4().hex}.jpg"
            )
            Image.new(
                "RGB", (self.screen_width, self.screen_height), (0, 0, 0)
            ).save(scaled_path, "JPEG")
            self.temp_scaled_files.add(scaled_path)
            height = self.screen_height
            width = self.screen_width

        with self.lock:
            if request_id == self._request_id:
                self.image_ready_path = scaled_path
                self.image_ready_height = height
                self.image_ready_scaled_width = width
                self.image_requested_index = page_index
                self.image_requested_offset_y = offset_y
                self._ready_request_id = request_id
                self.image_pending = False


    def on_zoom_changed(self, new_zoom_level):
        if new_zoom_level != self.zoom_level:
            self.zoom_level = new_zoom_level
            self._clear_scaled_cache()
            self.offset_y = 0
            self.display_image(
                self.image_list[self.current_image_index], self.offset_y
            )


    def update_image_control(self):
        with self.lock:
            path = self.image_ready_path
            height = self.image_ready_height
            width = self.image_ready_scaled_width
            offset_y = self.image_requested_offset_y
            index = self.image_requested_index
            request_id = self._ready_request_id

            self.image_ready_path = None
            self.image_ready_height = None
            self.image_ready_scaled_width = None
            self._ready_request_id = None

        if not path or height is None or width is None or self.image_control is None:
            return False

        # Ignore a result superseded by a newer navigation or zoom request.
        if request_id != self._request_id or index != self.current_image_index:
            return False

        old_displayed_path = self._displayed_scaled_path
        try:
            self.image_control.setImage(path)
            self.image_control.setWidth(width)
            center_x = max(0, (self.screen_width - width) // 2)
            self.image_control.setHeight(height)
            self.image_control.setPosition(center_x, -offset_y)
            self.max_offset_y = max(0, height - self.screen_height)
            self.last_height = height
            self._displayed_scaled_path = path

            if old_displayed_path and old_displayed_path != path:
                with self.cache_lock:
                    cached_paths = {entry[3] for entry in self.scaled_cache.values()}
                if old_displayed_path not in cached_paths:
                    self._remove_scaled_file(old_displayed_path)

        except RuntimeError as exc:
            if "does not exist" in str(exc):
                self.image_control = None
                return False
            raise

        if self._show_overlay_next_update:
            self._show_overlay_next_update = False
            self.show_index_overlay()

        return True
    
    def get_or_scale_image(self, image_path, page_index=None):
        if page_index is None:
            page_index = self.current_image_index

        zoom = self.zoom_level
        if self._archive_type:
            cache_key = ("archive", page_index, zoom)
        else:
            cache_key = ("folder", image_path, zoom)

        with self._scaled_cond:
            while cache_key in self._scaled_inflight:
                self._scaled_cond.wait()
            cached = self.scaled_cache.get(cache_key)
            if cached and os.path.isfile(cached[3]):
                self.scaled_cache.move_to_end(cache_key)
                return cached
            self._scaled_inflight.add(cache_key)

        raw_path = None
        pinned = False
        scaled_path = os.path.join(
            self._scaled_dir, f"scaled_{uuid.uuid4().hex}.jpg"
        )

        try:
            if self._archive_type:
                raw_path = self._raw_page_path(page_index)
                pinned = True
            else:
                raw_path = image_path

            target_width = max(1, int(self.screen_width * (zoom / 100.0)))
            with Image.open(raw_path) as source:
                image_width, image_height = source.size
                scaled_height = max(1, int(image_height * target_width / image_width))
                resampling = getattr(Image, "Resampling", Image).LANCZOS

                img = self.to_jpeg_compatible(source)
                img = img.resize((target_width, scaled_height), resampling)
                img.save(scaled_path, "JPEG")


            result = (None, scaled_height, target_width, scaled_path)
            self.temp_scaled_files.add(scaled_path)

            with self._scaled_cond:
                self.scaled_cache[cache_key] = result
                self.scaled_cache.move_to_end(cache_key)
                while len(self.scaled_cache) > self.cache_size:
                    _, evicted = self.scaled_cache.popitem(last=False)
                    self._remove_scaled_file(evicted[3])
                self._scaled_inflight.discard(cache_key)
                self._scaled_cond.notify_all()
            return result

        except Exception:
            try:
                if os.path.exists(scaled_path):
                    os.remove(scaled_path)
            except OSError:
                pass
            with self._scaled_cond:
                self._scaled_inflight.discard(cache_key)
                self._scaled_cond.notify_all()
            raise
        finally:
            if pinned:
                self._release_raw_page(page_index)

    #Fix "cannot write P as Jpeg errors"
    @staticmethod
    def to_jpeg_compatible(image):
        if image.mode in ("L", "RGB", "CMYK") and "transparency" not in image.info:
            return image  # No mode conversion needed

        has_transparency = (
            "A" in image.getbands() or "transparency" in image.info
        )

        if has_transparency:
            rgba = image.convert("RGBA")
            rgb = Image.new("RGB", rgba.size, (255, 255, 255))
            rgb.paste(rgba, mask=rgba.split()[-1])
            return rgb

        return image.convert("RGB")


    def preload_adjacent_images(self):
        indices = set()
        # Preload 2 pages forward
        if self.current_image_index + 1 < len(self.image_list):
            indices.add(self.current_image_index + 1)
        if self.current_image_index + 2 < len(self.image_list):
            indices.add(self.current_image_index + 2)
        # Preload 1 page backward
        if self.current_image_index - 1 >= 0:
            indices.add(self.current_image_index - 1)
        for idx in indices:
            path = self.image_list[idx]
            with self.cache_lock:
                if path in self.scaled_cache:
                    continue
            t = threading.Thread(target=self.get_or_scale_image, args=(path,))
            t.daemon = True
            t.start()

    
    
    #Library page progress helper Keeping This
    def save_progress(self):
        if (
            self.read_tracker
            and self.current_comic_path
            and self.image_list
        ):
            self.read_tracker.update_progress(
                self.current_comic_path,
                self.current_image_index + 1,  # tracker expects 1-based page
                len(self.image_list),
            )
    #New
    def _ensure_session_dir(self):
        if _is_sandboxed_platform():
            reader_temp_root = _get_addon_temp_dir("reader")
            tempfile.tempdir = reader_temp_root

            if self.temp_dir is not None:
                return

            self.temp_dir = tempfile.mkdtemp(
                prefix="kodics_session_",
                dir=reader_temp_root,
            )
        else:
            if self.temp_dir is not None:
                return
            # Preserve the currently working behavior on other platforms.
            self.temp_dir = tempfile.mkdtemp(prefix="kodics_session_")

        self._session_dir_owned = True
        self._raw_dir = os.path.join(self.temp_dir, "raw")
        self._scaled_dir = os.path.join(self.temp_dir, "scaled")
        os.makedirs(self._raw_dir, exist_ok=True)
        os.makedirs(self._scaled_dir, exist_ok=True)

    #New
    @staticmethod
    def _is_image_member(name):
        return name.lower().endswith((".jpg", ".jpeg", ".png"))
    #New
    def extract_comic_archive(self, archive_path, temp_dir=None):
        """List image members in the old lexicographic path order; extract nothing."""
        extension = os.path.splitext(archive_path)[1].lower()

        if extension == ".cbz":
            with zipfile.ZipFile(archive_path, "r") as archive:
                entries = [
                    (info.filename, ordinal)
                    for ordinal, info in enumerate(archive.infolist())
                    if not info.is_dir() and self._is_image_member(info.filename)
                ]
        elif extension == ".cbr":
            addon_dir = xbmcaddon.Addon(
                "script.image.kodicsMAX"
            ).getAddonInfo("path")
            unrar_path = self.get_unrar_binary_path(addon_dir)

            if sys.platform != "win32":
                os.chmod(unrar_path, 0o755)

            rarfile.UNRAR_TOOL = unrar_path
            with rarfile.RarFile(archive_path) as archive:
                entries = []
                for ordinal, info in enumerate(archive.infolist()):
                    is_dir = info.isdir() if callable(info.isdir) else info.isdir
                    if not is_dir and self._is_image_member(info.filename):
                        entries.append((info.filename, ordinal))
        else:
            raise ValueError("Unsupported comic archive type")

        # Matches the prior behavior of sorting extracted paths lexicographically.
        return sorted(entries, key=lambda entry: entry[0])
    #New
    def select_folder_and_image(self, comic_path=None):
        if comic_path:
            file_path = comic_path
        else:
            file_path = xbmcgui.Dialog().browse(
                1,
                "Select an Image or Comic Book File",
                "",
                ".jpg|.png|.jpeg|.cbz|.cbr|"
            )

        if not file_path:
            return None, None

        file_path = xbmcvfs.translatePath(file_path)
        extension = os.path.splitext(file_path)[1].lower()

        self._ensure_session_dir()

        if extension in (".cbz", ".cbr"):
            self.current_comic_path = file_path
            self._archive_type = extension[1:]
            self.image_list = self.extract_comic_archive(file_path)
            self.current_image_index = 0

            if self.image_list and self.read_tracker:
                progress = self.read_tracker.get_progress(file_path)
                if progress:
                    try:
                        saved_page = int(progress["current_page"])
                        self.current_image_index = max(
                            0, min(saved_page - 1, len(self.image_list) - 1)
                        )
                    except (KeyError, TypeError, ValueError):
                        self.current_image_index = 0

            return (
                self.temp_dir,
                self.image_list[self.current_image_index]
                if self.image_list else None
            )

        self._archive_type = None
        folder_path = os.path.dirname(file_path)
        self.image_list = sorted(
            os.path.join(folder_path, filename)
            for filename in os.listdir(folder_path)
            if filename.lower().endswith((".jpg", ".jpeg", ".png"))
        )

        try:
            self.current_image_index = self.image_list.index(file_path)
        except ValueError:
            self.current_image_index = 0

        return folder_path, file_path

    #Keeping this    
    def get_unrar_binary_path(self, addon_dir):
        """Determine the correct unrar binary path based on architecture"""
        arch = platform.machine()
        
        # Map architecture to directory
        arch_map = {
            'aarch64': 'aarch64',
            'x86_64': 'x86_64',
            'AMD64': 'x86_64',  # Windows alternative name
        }
        
        if arch not in arch_map:
            raise RuntimeError(
                f"Unsupported architecture: {arch}. "
                f"This addon only supports aarch64 and x86_64."
            )
        
        arch_dir = arch_map[arch]
        unrar_path = os.path.join(addon_dir, 'bin', arch_dir, 'unrar')
        
        # Verify the binary exists
        if not os.path.exists(unrar_path):
            raise RuntimeError(
                f"UnRAR binary not found at: {unrar_path}"
            )
        
        return unrar_path


    def show_index_overlay(self):
    # Remove existing overlay first (safely, from main thread)
        self._remove_overlay_now()

        if not self.image_list:
            return

        overlay_text = f"{self.current_image_index + 1} / {len(self.image_list)}"
        label_width = max(1, int(self.screen_width * 0.08))
        label_height = max(1, int(self.screen_height * 0.06))

        x = self.screen_width - label_width - int(self.screen_width * 0.01)
        y = self.screen_height - label_height - int(self.screen_height * 0.01)
        #label_width = 75
        #label_height = 30
        padding = 10
        #x = self.screen_width - label_width - 100  # 20px from right edge
        #y = self.screen_height - label_height - 80  

        # Create background
        self._ensure_session_dir()
        bg_img = os.path.join(self.temp_dir, 'kodi_overlay_bg.png')
        from PIL import Image as PILImage
        img = PILImage.new("RGBA", (label_width, label_height), (192, 192, 192, 220))
        img.save(bg_img)

        self.overlay_bg = xbmcgui.ControlImage(
            x, y, label_width, label_height, bg_img
        )
        self.addControl(self.overlay_bg)

        # Create label
        try:
            self.overlay_label = xbmcgui.ControlLabel(
                x + padding, y + padding, 
                label_width - 2*padding, label_height - 2*padding,
                overlay_text,
                textColor='0xFF000000',  # Black text
                alignment=4 | 8,  # CENTER_X | CENTER_Y only
                font="font48"
            )
        except TypeError:
            self.overlay_label = xbmcgui.ControlLabel(
                x + padding, y + padding, 
                label_width - 2*padding, label_height - 2*padding,
                overlay_text,
                textColor='0xFFFFFFFF',
                alignment=4 | 8
            )
        self.addControl(self.overlay_label)
        
        # **Schedule removal via main loop, not daemon thread**
        #self.overlay_remove_time = xbmc.getGlobalIdleTime()
        self.overlay_show_time = time.time()

    def _remove_overlay_now(self):
        """Safely remove overlay controls from main thread"""
        for ctrl in [self.overlay_bg, self.overlay_label]:
            if ctrl:
                try:
                    self.removeControl(ctrl)
                except Exception:
                    pass
        self.overlay_bg = None
        self.overlay_label = None

    
    def onAction(self, action):
        #xbmc.log(f"Kodics DEBUG: action = {action.getId()}", xbmc.LOGINFO)
        action_id = action.getId()
        page_changed = False
        button_code = action.getButtonCode()
        amount1 = action.getAmount1()
        amount2 = action.getAmount2()
        

        if action_id == 10:  # Mouse action
            #xbmc.log(f"Kodics DEBUG: action methods = {[m for m in dir(action) if not m.startswith('_')]}", xbmc.LOGINFO)
            for method_name in dir(action):
                if not method_name.startswith('_'):
                    try:
                        value = getattr(action, method_name)()
                        #xbmc.log(f"Kodics DEBUG: {method_name}() = {value}", xbmc.LOGINFO)
                    except:
                        pass

        if action_id == 100:  # ACTION_MOUSE_LEFT_CLICK
            xbmc.log("LEFT CLICK detected", xbmc.LOGINFO)
        elif action_id == 101:  # ACTION_MOUSE_RIGHT_CLICK
            xbmc.log("RIGHT CLICK detected", xbmc.LOGINFO)
        elif action_id == 104:  # ACTION_MOUSE_WHEEL_UP
            xbmc.log("WHEEL UP detected", xbmc.LOGINFO)
        elif action_id == 105:  # ACTION_MOUSE_WHEEL_DOWN
            xbmc.log("WHEEL DOWN detected", xbmc.LOGINFO)
        elif action_id == 102:  # ACTION_MOUSE_MIDDLE_CLICK
            xbmc.log("MIDDLE CLICK detected", xbmc.LOGINFO)

        
        if action_id == xbmcgui.ACTION_SELECT_ITEM:
            old_zoom = self.zoom_level
            
            if self.settings_manager.show_menu():  # show_menu() returns True if "Close Content" selected
                self.running = False
                self.close()
                return
            
            # Menu closed normally — check if zoom changed
            new_zoom = self.settings_manager.get_setting('zoom_level', 100)
            if new_zoom != old_zoom:
                self.on_zoom_changed(new_zoom)
            
            self.volume_manager.apply_mute_setting()
            return

        old_page_index = self.current_image_index

        # ✅ LOCK ALL INDEX/OFFSET MODIFICATIONS
        with self.lock:
            # Next page (right arrow or next item)
            if action_id in (ACTION_MOVE_RIGHT, ACTION_NEXT_ITEM):
                if self.current_image_index < len(self.image_list) - 1:
                    self.current_image_index += 1
                    self.offset_y = 0
                    image_path = self.image_list[self.current_image_index]
                    page_changed = True
            
            # Previous page (left arrow or prev item)
            elif action_id in (ACTION_MOVE_LEFT, ACTION_PREV_ITEM):
                if self.current_image_index > 0:
                    self.current_image_index -= 1
                    self.offset_y = 0
                    image_path = self.image_list[self.current_image_index]
                    page_changed = True
            
            # Scroll up (up arrow or page up)
            elif action_id in (ACTION_MOVE_UP, ACTION_PAGE_UP):
                old_offset = self.offset_y
                scroll_distance = self.settings_manager.get_setting('scroll_distance', 100) if self.settings_manager else 100
                self.offset_y = max(0, self.offset_y - scroll_distance)
                if self.offset_y != old_offset:
                    image_path = self.image_list[self.current_image_index]
            
            # Scroll down (down arrow or page down)
            elif action_id in (ACTION_MOVE_DOWN, ACTION_PAGE_DOWN):
                old_offset = self.offset_y
                scroll_distance = self.settings_manager.get_setting('scroll_distance', 100) if self.settings_manager else 100
                self.offset_y = min(self.max_offset_y, self.offset_y + scroll_distance)
                if self.offset_y != old_offset:
                    image_path = self.image_list[self.current_image_index]
            
            # Exit viewer (back or previous menu)
            elif action_id in (ACTION_NAV_BACK, ACTION_PREVIOUS_MENU):
                # Before script finishes
                home_window = xbmcgui.Window(10000)
                #home_window.setProperty('fitwidth_done', 'true')



                self.running = False
                return

            # Mouse: Left click = previous image
            elif action_id == ACTION_MOUSE_LEFT_CLICK:
                if self.current_image_index > 0:
                    self.current_image_index -= 1
                    self.offset_y = 0
                image_path = self.image_list[self.current_image_index]
                self._show_overlay_next_update = True

            # Mouse: Right click = next image
            elif action_id == ACTION_MOUSE_RIGHT_CLICK:
                if self.current_image_index < len(self.image_list) - 1:
                    self.current_image_index += 1
                    self.offset_y = 0
                image_path = self.image_list[self.current_image_index]
                self._show_overlay_next_update = True

            # Mouse: Wheel up = scroll up
            elif action_id == ACTION_MOUSE_WHEEL_UP:
                self.offset_y = max(0, self.offset_y - self.settings_manager.get_setting('scroll_distance', 100))
                image_path = self.image_list[self.current_image_index]

            # Mouse: Wheel down = scroll down
            elif action_id == ACTION_MOUSE_WHEEL_DOWN:
                self.offset_y = min(self.max_offset_y, self.offset_y + self.settings_manager.get_setting('scroll_distance', 100))
                image_path = self.image_list[self.current_image_index]

            # Mouse: Middle click = show menu
            # Mouse: Middle click = show menu
            elif action_id == ACTION_MOUSE_MIDDLE_CLICK:
                old_zoom = self.zoom_level
                
                if self.settings_manager.show_menu():
                    self.running = False
                    self.close()
                    return
                
                # Menu closed normally — check if zoom changed
                new_zoom = self.settings_manager.get_setting('zoom_level', 100)
                if new_zoom != old_zoom:
                    self.on_zoom_changed(new_zoom)
                
                self.volume_manager.apply_mute_setting()
                return

            
            else:
                return  # Unhandled action

        #save current page info for library
        if self.current_image_index != old_page_index:
            self.save_progress()



        # ✅ NOW display_image() outside the lock (so load thread can acquire lock independently)
        if 'image_path' in locals():
            self.display_image(image_path, self.offset_y)
        
        # Show page number overlay when page changes
        if page_changed:
            self._show_overlay_next_update = True


    def cleanup_temp_scaled_files(self):
        # Only delete paths under this reader's owned session directory.
        for path in list(self.temp_scaled_files):
            self._remove_scaled_file(path)
        self.temp_scaled_files.clear()
        with self.cache_lock:
            self.scaled_cache.clear()

    #New Workers for Cache
    def _start_worker(self, target, args=(), name="kodics-worker"):
        with self._workers_lock:
            if self._stopping:
                return False
            thread = threading.Thread(
                target=self._worker_entry,
                args=(target, args),
                name=name,
                daemon=True,
            )
            self._workers.add(thread)
            thread.start()
            return True

    def _worker_entry(self, target, args):
        try:
            target(*args)
        except Exception as exc:
            xbmc.log(f"[kodics] Background worker failed: {exc}", xbmc.LOGERROR)
        finally:
            with self._workers_lock:
                self._workers.discard(threading.current_thread())

    def _shutdown_workers(self):
        with self._raw_cond:
            self._stopping = True
            self._raw_cond.notify_all()

        # No workers are started after _stopping is set. Join outside the set lock.
        while True:
            with self._workers_lock:
                workers = list(self._workers)
            if not workers:
                break
            for worker in workers:
                if worker is not threading.current_thread():
                    worker.join()
    #New for the Workers
    def _extract_archive_page(self, page_index):
        member_name, ordinal = self.image_list[page_index]
        suffix = os.path.splitext(member_name)[1].lower()
        if suffix not in (".jpg", ".jpeg", ".png"):
            suffix = ".img"

        destination = os.path.join(
            self._raw_dir, f"page_{page_index}_{uuid.uuid4().hex}{suffix}"
        )
        partial = destination + ".part"

        try:
            if self._archive_type == "cbz":
                with zipfile.ZipFile(self.current_comic_path, "r") as archive:
                    info = archive.infolist()[ordinal]
                    with archive.open(info, "r") as source, open(partial, "wb") as out:
                        shutil.copyfileobj(source, out)
            else:
                addon_dir = xbmcaddon.Addon(
                    "script.image.kodicsMAX"
                ).getAddonInfo("path")
                rarfile.UNRAR_TOOL = self.get_unrar_binary_path(addon_dir)
                

                with rarfile.RarFile(self.current_comic_path) as archive:
                    info = archive.infolist()[ordinal]
                    with archive.open(info) as source, open(partial, "wb") as out:
                        shutil.copyfileobj(source, out)

            os.replace(partial, destination)
            return destination
        except Exception:
            for path in (partial, destination):
                try:
                    if os.path.exists(path):
                        os.remove(path)
                except OSError:
                    pass
            raise
    #New for the Workers
    def _raw_page_path(self, page_index):
        """Return a pinned extracted path for an archive page."""
        with self._raw_cond:
            while True:
                if self._stopping:
                    raise RuntimeError("Reader is shutting down")

                cached = self._raw_cache.get(page_index)
                if cached and os.path.isfile(cached):
                    self._raw_cache.move_to_end(page_index)
                    self._raw_pins[page_index] = self._raw_pins.get(page_index, 0) + 1
                    return cached

                if page_index in self._raw_inflight:
                    self._raw_cond.wait()
                    continue

                # Reserve a cache slot before extracting. Never evict a pinned page.
                if len(self._raw_cache) + len(self._raw_inflight) >= self._raw_cache_limit:
                    current = self.current_image_index
                    wanted = set(range(max(0, current - 1),
                                       min(len(self.image_list), current + 3)))
                    candidates = [
                        idx for idx in self._raw_cache
                        if self._raw_pins.get(idx, 0) == 0
                    ]
                    if not candidates:
                        self._raw_cond.wait()
                        continue

                    victim = next(
                        (idx for idx in candidates if idx not in wanted),
                        candidates[0],
                    )
                    old_path = self._raw_cache.pop(victim)
                    self._raw_pins.pop(victim, None)
                    try:
                        os.remove(old_path)
                    except OSError:
                        pass

                self._raw_inflight.add(page_index)
                break

        try:
            path = self._extract_archive_page(page_index)
        except Exception:
            with self._raw_cond:
                self._raw_inflight.discard(page_index)
                self._raw_cond.notify_all()
            raise

        with self._raw_cond:
            self._raw_inflight.discard(page_index)
            self._raw_cache[page_index] = path
            self._raw_pins[page_index] = 1
            self._raw_cond.notify_all()
        return path

    def _release_raw_page(self, page_index):
        with self._raw_cond:
            count = self._raw_pins.get(page_index, 0)
            if count <= 1:
                self._raw_pins.pop(page_index, None)
            else:
                self._raw_pins[page_index] = count - 1
            self._raw_cond.notify_all()

    def _remove_scaled_file(self, path):
        if not path or path == self._displayed_scaled_path or not self.temp_dir:
            return
        try:
            if os.path.commonpath((os.path.realpath(path),
                                   os.path.realpath(self.temp_dir))) == os.path.realpath(self.temp_dir):
                if os.path.isfile(path):
                    os.remove(path)
                self.temp_scaled_files.discard(path)
        except (OSError, ValueError):
            pass

    def _clear_scaled_cache(self):
        with self._scaled_cond:
            old_entries = list(self.scaled_cache.values())
            self.scaled_cache.clear()
            for entry in old_entries:
                self._remove_scaled_file(entry[3])
            self._scaled_cond.notify_all()



    

    def run(self):
        try:
            if self.startup_comic_path:
                folder_path, image_path = self.select_folder_and_image(
                    self.startup_comic_path
                )
            else:
                folder_path, image_path = self.select_folder_and_image()

            if not image_path:
                xbmcgui.Dialog().ok(
                    "Error", "No image or CBZ/CBR file selected."
                )
                return

            self.display_image(image_path, self.offset_y)
            self._show_overlay_next_update = True
            self.overlay_remove_time = None
            self.show()
            ready_signaled = False

            while self.running:
                with self._worker_error_lock:
                    worker_error = self._worker_error
                    self._worker_error = None
                if worker_error:
                    xbmcgui.Dialog().ok("Error", worker_error)

                with self.lock:
                    ready = (
                        self.image_ready_path is not None
                        and not self.image_pending
                    )

                if ready and self.update_image_control():
                    if not ready_signaled:
                        xbmcgui.Window(10000).setProperty(
                            "fitwidth_ready", "true"
                        )
                        ready_signaled = True

                    if self._show_overlay_next_update:
                        self.show_index_overlay()
                        self._show_overlay_next_update = False
                        self.overlay_show_time = time.time()

                    self.preload_adjacent_images()

                if self.overlay_show_time is not None:
                    elapsed = (time.time() - self.overlay_show_time) * 1000
                    if elapsed >= 1000:
                        self._remove_overlay_now()
                        self.overlay_show_time = None

                xbmc.sleep(50)

        finally:
            self.running = False

            for cleanup in (
                self._shutdown_workers,
                self.save_progress,
                self.cleanup_temp_scaled_files,
            ):
                try:
                    cleanup()
                except Exception as exc:
                    xbmc.log(
                        f"FitWidth cleanup failed: {exc}",
                        xbmc.LOGERROR
                    )

            try:
                if (
                    self._session_dir_owned
                    and self.temp_dir
                    and os.path.basename(self.temp_dir).startswith(
                        "kodics_session_"
                    )
                    and os.path.isdir(self.temp_dir)
                ):
                    shutil.rmtree(self.temp_dir, ignore_errors=True)
            except Exception as exc:
                xbmc.log(
                    f"FitWidth temp cleanup failed: {exc}",
                    xbmc.LOGERROR
                )
            finally:
                self.temp_dir = None
                self._session_dir_owned = False

            try:
                self.close()
            except Exception as exc:
                xbmc.log(
                    f"FitWidth close failed: {exc}",
                    xbmc.LOGERROR
                )


# --- Main Entrypoint ---
# Get addon instance and profile path
addon = xbmcaddon.Addon('script.image.kodicsMAX')
addon_profile = addon.getAddonInfo('profile')
startup_path = None


if len(sys.argv) > 2:
    startup_path = sys.argv[2]

    if xbmcvfs.exists(startup_path):
        xbmc.log(
            f'KodicsMAX: Startup comic: {startup_path}',
            xbmc.LOGINFO
        )
    else:
        xbmc.log(
            f'KodicsMAX: Startup path does not exist: {startup_path}',
            xbmc.LOGERROR
        )
        startup_path = None

settings_mgr = SettingsManager(addon_profile)
volume_mgr = VolumeManager(settings_mgr)
volume_mgr.maybe_mute_volume()
try:
    viewer = FitWidthImageViewer()
    viewer.settings_manager = settings_mgr  # Pass settings to viewer
    viewer.volume_manager = volume_mgr
    viewer.startup_comic_path = startup_path
    settings_mgr.viewer_instance = viewer 
    viewer.read_tracker = ReadTracker(
        xbmcvfs.translatePath(addon_profile)
    )


    viewer.run()
except Exception:
    xbmc.log(traceback.format_exc(), xbmc.LOGERROR)
finally:
    volume_mgr.maybe_restore_volume()
    xbmcgui.Window(10000).setProperty("fitwidth_done", "true")  

