import xbmc
import xbmcgui
import xbmcvfs
import xbmcaddon
import platform
import os
import sys
import zipfile
import time
# Add lib folder to path so rarfile can be imported
addon_dir = xbmcaddon.Addon().getAddonInfo('path')
lib_path = os.path.join(addon_dir, 'lib')
if lib_path not in sys.path:
    sys.path.insert(0, lib_path)

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

class SettingsManager:
    """Handles loading, saving, and displaying settings from settings.json"""
    
    def __init__(self):
        self.addon = xbmcaddon.Addon()
        self.addon_profile = xbmcvfs.translatePath(self.addon.getAddonInfo('profile'))
        self.settings_file = os.path.join(self.addon_profile, 'settings.json')
        self.default_settings = {
            'mute_audio': True,
            'scroll_distance': 100,
            'zoom_level': 100
        }
        self.settings = self.load_settings()
    
    def load_settings(self):
        """Load settings from settings.json, or create with defaults if missing"""
        if not os.path.exists(self.addon_profile):
            os.makedirs(self.addon_profile, exist_ok=True)
        
        if os.path.exists(self.settings_file):
            try:
                with open(self.settings_file, 'r') as f:
                    loaded = json.load(f)
                    # Merge with defaults to handle new settings
                    settings = self.default_settings.copy()
                    settings.update(loaded)
                    return settings
            except Exception as e:
               # xbmc.log(f"[Kodics] Error loading settings: {e}", xbmc.LOGERROR)
                return self.default_settings.copy()
        else:
            self.save_settings(self.default_settings.copy())
            return self.default_settings.copy()
    
    def save_settings(self, settings_dict):
        """Save settings to settings.json"""
        try:
            os.makedirs(self.addon_profile, exist_ok=True)
            with open(self.settings_file, 'w') as f:
                json.dump(settings_dict, f, indent=2)
            self.settings = settings_dict.copy()
        except Exception as e:
            xbmc.log(f"[Kodics] Error saving settings: {e}", xbmc.LOGERROR)
    
    def get(self, key, default=None):
        """Get a setting value"""
        return self.settings.get(key, default)
    
    def set(self, key, value):
        """Set a setting value and save"""
        self.settings[key] = value
        self.save_settings(self.settings)
    
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
                self.settings['mute_audio'] = not self.settings['mute_audio']
                self.save_settings(self.settings)
                if self.viewer_instance and hasattr(self.viewer_instance, 'on_setting_changed'):
                    self.viewer_instance.on_setting_changed('mute_audio', self.settings['mute_audio'])
            elif selection == 1:  # Change Scroll Distance
                scroll_options = ['25 px', '50 px', '75 px', '100 px', '150 px', '300 px', '600 px', '1000 px']
                scroll_values = [25, 50, 75, 100, 150, 300, 600, 1000]
                current_idx = scroll_values.index(self.settings['scroll_distance']) if self.settings['scroll_distance'] in scroll_values else 3
                
                sel = dialog.select("Scroll Distance", scroll_options, preselect=current_idx)
                if sel != -1:
                    self.settings['scroll_distance'] = scroll_values[sel]
                    self.save_settings(self.settings)
                    if self.viewer_instance and hasattr(self.viewer_instance, 'on_setting_changed'):
                        self.viewer_instance.on_setting_changed('scroll_distance', self.settings['scroll_distance'])
            elif selection == 2:  # Change Zoom Level
                zoom_options = ['100%', '95%', '90%', '70%', '60%', '50%', '40%', '105%', '110%', '115%', '120%']
                zoom_values = [100, 95, 90, 70, 60, 50, 40, 105, 110, 115, 120]
                current_idx = zoom_values.index(self.settings['zoom_level']) if self.settings['zoom_level'] in zoom_values else 0
            
                sel = dialog.select("Zoom Level", zoom_options, preselect=current_idx)
                if sel != -1:
                    self.settings['zoom_level'] = zoom_values[sel]
                    self.save_settings(self.settings)
                    if self.viewer_instance and hasattr(self.viewer_instance, 'on_setting_changed'):
                        self.viewer_instance.on_setting_changed('zoom_level', self.settings['zoom_level'])
            elif selection == 4:  # Close Content
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
        mute_audio = self.settings_manager.get('mute_audio', True)
        
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
        mute_audio = self.settings_manager.get('mute_audio', True)
        
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

        self.image_list = []
        self.current_image_index = 0
        self.offset_y = 0
        self.max_offset_y = 0
        self.running = True
        self.temp_dir = None
        self.scaled_cache = OrderedDict()
        self.cache_size = 5
        self.cache_lock = threading.Lock()
        self.temp_scaled_files = set()
        # For threading/image loading
        self.image_pending = False
        self.image_ready_path = None
        self.image_ready_height = None
        self.image_requested_index = None
        self.image_requested_offset_y = None
        self.lock = threading.Lock()
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
            self.image_pending = True
            self.image_requested_index = self.current_image_index
            self.image_requested_offset_y = offset_y
        t = threading.Thread(target=self.load_and_scale_image, args=(image_path,))
        t.daemon = True
        t.start()
        #self.offset_y = offset_y

    def load_and_scale_image(self, image_path):
        scaled_image_bytes, scaled_height, scaled_width, temp_scaled_path = self.get_or_scale_image(image_path)
        with self.lock:
            self.image_ready_path = temp_scaled_path
            self.image_ready_height = scaled_height
            self.image_ready_scaled_width = scaled_width  # ← Add this line
            self.image_pending = False


    def on_zoom_changed(self, new_zoom_level):
        """Called when zoom level changes in settings menu"""
        if new_zoom_level != self.zoom_level:
            self.zoom_level = new_zoom_level
            
            # Clear the scaled image cache for this image
            with self.lock:
                self.scaled_cache.clear()
                self.current_scroll = 0  # Reset scroll position
            
            # Reload the current image at the new zoom level
            self.display_image(self.image_list[self.current_image_index], 0)


    def update_image_control(self):
        with self.lock:
            path = self.image_ready_path
            height = self.image_ready_height
            scaled_width = self.image_ready_scaled_width
            offset_y = self.image_requested_offset_y
            index = self.image_requested_index
            self.image_ready_path = None
            self.image_ready_height = None
            self.image_ready_scaled_width = None
        
        # ✅ CRITICAL: Check if control still exists before using it
        if self.image_control is None:
            return
        
        if path and height is not None and scaled_width is not None:
            try:
                xbmc.log(f"[kodics] Updating control: screen_width={self.screen_width}, scaled_width={scaled_width}, scaled_height={height}", xbmc.LOGINFO)
                self.image_control.setImage(path)
                # Set width to scaled_width (not screen_width) to prevent stretching at zoom < 100%
                self.image_control.setWidth(scaled_width)
                # Center horizontally
                center_x = max(0, (self.screen_width - scaled_width) // 2)
                if height != self.last_height:
                    self.image_control.setHeight(height)
                    self.last_height = height
                self.image_control.setPosition(center_x, -offset_y)
                self.max_offset_y = max(0, height - self.screen_height)
                xbmc.log(f"[kodics] Control set to {scaled_width}x{height}, centered at x={center_x}", xbmc.LOGINFO)
            except RuntimeError as e:
                # ✅ Gracefully handle removal during update
                if "does not exist" in str(e):
                    #xbmc.log(f"[kodics] Image control removed during update: {e}", xbmc.LOGINFO)
                    self.image_control = None
                    return
                raise
        
        # Show overlay if requested (set by page change)
        if self._show_overlay_next_update:
            self._show_overlay_next_update = False
            self.show_index_overlay()


    def get_or_scale_image(self, image_path):
        # Build cache key with zoom level to prevent collisions
        cache_key = f"{image_path}_{self.zoom_level}"
        
        with self.cache_lock:
            cached = self.scaled_cache.get(cache_key)
            if cached:
                self.scaled_cache.move_to_end(cache_key)
                return cached  # Returns (result_bytes, result_height, scaled_width, temp_scaled_path)

        try:
            # Calculate target width based on zoom level
            target_width = int(self.screen_width * (self.zoom_level / 100))
            
            with Image.open(image_path) as img:
                image_width, image_height = img.size
                scale_factor = target_width / image_width
                scaled_width = target_width
                scaled_height = int(image_height * scale_factor)
                img = img.resize((scaled_width, scaled_height), Image.LANCZOS)
                memfile = BytesIO()
                img.save(memfile, "JPEG")
                memfile.seek(0)
                result_bytes = memfile
                result_height = scaled_height
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Unable to display image: {str(e)}")
            blank = BytesIO()
            Image.new("RGB", (self.screen_width, self.screen_height), (0, 0, 0)).save(blank, "JPEG")
            blank.seek(0)
            result_bytes = blank
            result_height = self.screen_height
            scaled_width = self.screen_width  # Fallback for error case

        # Temp filename includes zoom level
        temp_scaled_path = os.path.join(tempfile.gettempdir(), f"kodics_scaled_{hash(image_path)}_{self.zoom_level}.jpg")
        try:
            with open(temp_scaled_path, "wb") as f:
                f.write(result_bytes.getbuffer())
            self.temp_scaled_files.add(temp_scaled_path)
        
            with Image.open(temp_scaled_path) as verify_img:
                actual_width, actual_height = verify_img.size
                xbmc.log(f"[kodics] Saved image dimensions: {actual_width}x{actual_height}, expected: {scaled_width}x{scaled_height}, zoom: {self.zoom_level}%", xbmc.LOGINFO)
        except Exception as e:
            xbmcgui.Dialog().ok("Error", f"Unable to write temp scaled image: {str(e)}")

        result = (result_bytes, result_height, scaled_width, temp_scaled_path)

        with self.cache_lock:
            self.scaled_cache[cache_key] = result
            self.scaled_cache.move_to_end(cache_key)
            if len(self.scaled_cache) > self.cache_size:
                self.scaled_cache.popitem(last=False)
        return result


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

    def select_folder_and_image(self):
        dialog = xbmcgui.Dialog()
        default_path = ""
        file_path = dialog.browse(1, "Select an Image or Comic Book File", default_path, ".jpg|.png|.jpeg|.cbz|.cbr|")
        if not file_path:
            return None, None
        if file_path.lower().endswith((".cbz", ".cbr")):
            self.temp_dir = tempfile.mkdtemp()
            self.extract_comic_archive(file_path, self.temp_dir)

            folder_path = self.temp_dir
            self.image_list = []
            for root, dirs, files in os.walk(folder_path):
                for f in files:
                    if f.lower().endswith((".jpg", ".png", ".jpeg")):
                        self.image_list.append(os.path.join(root, f))
            self.image_list.sort()
            self.current_image_index = 0
            return folder_path, self.image_list[0] if self.image_list else None

        folder_path = os.path.dirname(file_path)
        self.image_list = [
            os.path.join(folder_path, f)
            for f in os.listdir(folder_path)
            if f.lower().endswith((".jpg", ".png", ".jpeg"))
        ]
        self.image_list.sort()
        self.current_image_index = self.image_list.index(file_path)
        return folder_path, file_path


    def extract_comic_archive(self, archive_path, temp_dir):
        """Extract comic archive (.cbz or .cbr) to temp directory"""
        if archive_path.endswith('.cbz'):
            with zipfile.ZipFile(archive_path, 'r') as zip_ref:
                zip_ref.extractall(temp_dir)
        elif archive_path.endswith('.cbr'):
            addon_dir = xbmcaddon.Addon().getAddonInfo('path')
            unrar_path = self.get_unrar_binary_path(addon_dir)
            
            # Make sure it's executable on Linux/macOS
            if not sys.platform == 'win32':
                os.chmod(unrar_path, 0o755)
            
            # Use rarfile with the bundled unrar
            rarfile.UNRAR_TOOL = unrar_path
            with rarfile.RarFile(archive_path) as rar_ref:
                rar_ref.extractall(temp_dir)

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
        bg_img = os.path.join(tempfile.gettempdir(), 'kodi_overlay_bg.png')
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
            new_zoom = self.settings_manager.get('zoom_level', 100)
            if new_zoom != old_zoom:
                self.on_zoom_changed(new_zoom)
            
            self.volume_manager.apply_mute_setting()
            return


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
                scroll_distance = self.settings_manager.get('scroll_distance', 100) if self.settings_manager else 100
                self.offset_y = max(0, self.offset_y - scroll_distance)
                if self.offset_y != old_offset:
                    image_path = self.image_list[self.current_image_index]
            
            # Scroll down (down arrow or page down)
            elif action_id in (ACTION_MOVE_DOWN, ACTION_PAGE_DOWN):
                old_offset = self.offset_y
                scroll_distance = self.settings_manager.get('scroll_distance', 100) if self.settings_manager else 100
                self.offset_y = min(self.max_offset_y, self.offset_y + scroll_distance)
                if self.offset_y != old_offset:
                    image_path = self.image_list[self.current_image_index]
            
            # Exit viewer (back or previous menu)
            elif action_id in (ACTION_NAV_BACK, ACTION_PREVIOUS_MENU):
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
                self.offset_y = max(0, self.offset_y - self.settings_manager.get('scroll_distance', 100))
                image_path = self.image_list[self.current_image_index]

            # Mouse: Wheel down = scroll down
            elif action_id == ACTION_MOUSE_WHEEL_DOWN:
                self.offset_y = min(self.max_offset_y, self.offset_y + self.settings_manager.get('scroll_distance', 100))
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
                new_zoom = self.settings_manager.get('zoom_level', 100)
                if new_zoom != old_zoom:
                    self.on_zoom_changed(new_zoom)
                
                self.volume_manager.apply_mute_setting()
                return

            
            else:
                return  # Unhandled action
        
        # ✅ NOW display_image() outside the lock (so load thread can acquire lock independently)
        if 'image_path' in locals():
            self.display_image(image_path, self.offset_y)
        
        # Show page number overlay when page changes
        if page_changed:
            self._show_overlay_next_update = True


    def cleanup_temp_scaled_files(self):
        for path in self.temp_scaled_files:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception:
                pass

    def run(self):
        try:
            folder_path, image_path = self.select_folder_and_image()
            if not image_path:
                xbmcgui.Dialog().ok("Error", "No image or CBZ/CBR file selected.")
                return

            # Display first image
            self.display_image(image_path, self.offset_y)
            # Show overlay for first image
            self._show_overlay_next_update = True
            self.overlay_remove_time = None  
            self.show()
            while self.running:
                with self.lock:
                    ready = self.image_ready_path is not None and not self.image_pending
                if ready:
                    self.update_image_control()
                    
                    if self._show_overlay_next_update:
                        self.show_index_overlay()
                        self._show_overlay_next_update = False
                        self.overlay_show_time = time.time()
                    
                    self.preload_adjacent_images()

                if self.overlay_show_time is not None:
                    elapsed = (time.time() - self.overlay_show_time) * 1000  # Convert to ms
                    if elapsed >= 1000:
                        self._remove_overlay_now()
                        self.overlay_show_time = None

                xbmc.sleep(50)
        finally:
            if self.temp_dir and os.path.exists(self.temp_dir):
                for f in os.listdir(self.temp_dir):
                    path = os.path.join(self.temp_dir, f)
                    if os.path.isfile(path) or os.path.islink(path):
                        os.remove(path)
                    elif os.path.isdir(path):
                        shutil.rmtree(path)
                os.rmdir(self.temp_dir)
            self.cleanup_temp_scaled_files()
            self.close()

# --- Main Entrypoint ---

settings_mgr = SettingsManager()
volume_mgr = VolumeManager(settings_mgr)
volume_mgr.maybe_mute_volume()
try:
    viewer = FitWidthImageViewer()
    viewer.settings_manager = settings_mgr  # Pass settings to viewer
    viewer.volume_manager = volume_mgr
    settings_mgr.viewer_instance = viewer 
    viewer.run()
finally:
    volume_mgr.maybe_restore_volume()  

