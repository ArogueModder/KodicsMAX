# -*- coding: utf-8 -*-
import os
import sys
import xbmc
import xbmcaddon
import xbmcvfs
import xbmcgui
import subprocess

addon = xbmcaddon.Addon()
addon_dir = xbmcvfs.translatePath(addon.getAddonInfo('path'))
addon_profile = xbmcvfs.translatePath(addon.getAddonInfo('profile'))

# Add windows directory to path
sys.path.insert(0, os.path.join(addon_dir, 'windows'))



from home import HomeWindow
from library import LibraryWindow
from settings import SettingsWindow


class SettingsManagerLibrary:
    """Simple settings manager for the library."""
    def __init__(self, profile_path):
        self.profile_path = profile_path
        self.settings_file = os.path.join(profile_path, 'settings.json')
        self.settings = self._load_settings()
    
    def _load_settings(self):
        if os.path.exists(self.settings_file):
            import json
            try:
                with open(self.settings_file, 'r') as f:
                    return json.load(f)
            except:
                return {}
        return {}
    
    def get_setting(self, key, default=''):
        return self.settings.get(key, default)
    
    def set_setting(self, key, value):
        self.settings[key] = value
        self._save_settings()
    
    def _save_settings(self):
        import json
        os.makedirs(self.profile_path, exist_ok=True)
        with open(self.settings_file, 'w') as f:
            json.dump(self.settings, f)


def main():
    xbmc.log('KodicsMAX starting', xbmc.LOGINFO)
    xbmc.log(f'Addon directory: {addon_dir}', xbmc.LOGINFO)
    
    settings_manager = SettingsManagerLibrary(addon_profile)

    fitwidth_script = os.path.join(
        addon_dir,
        'FitWidthImageViewer.py'
    )


    while True:
        # Show home window
        home_window = HomeWindow('home.xml', addon_dir, 'default')
        result = home_window.show()

        if not result or result == 'exit':
            xbmc.log('KodicsMAX exiting', xbmc.LOGINFO)
            break

        xbmc.log(f'Home selection: {result}', xbmc.LOGINFO)

        # Handle navigation
        if result == 'library':
            base_dir = settings_manager.get_setting('library_base_dir', '')
            if not base_dir:
                dialog = xbmcgui.Dialog()
                dialog.notification(
                    'KodicsMAX',
                    'Please set Library Base Directory in Settings'
                )
                continue

            library_directory = base_dir

            # Keep showing the library after each comic closes.
            while True:
                library_window = LibraryWindow(
                    'library.xml',
                    addon_dir,
                    'default'
                )
                library_window.addon_profile = addon_profile

                selected_comic = library_window.show(
                    base_dir,
                    library_directory
                )

                # No comic selected means the user backed out of the library.
                if not selected_comic:
                    break

                # Save the directory before launching the reader.
                library_directory = library_window.current_directory

                xbmc.log(
                    f'KodicsMAX: Comic selected: {selected_comic}',
                    xbmc.LOGINFO
                )

                #loading indicator
                progress = xbmcgui.DialogProgressBG()
                progress.create('Loading Content', 'Preparing pages')

                bg_window = xbmcgui.Window(10000)
                bg_window.setProperty('fitwidth_done', 'false')
                bg_window.setProperty('fitwidth_ready', 'false')

                xbmc.executebuiltin(
                    f'RunScript("{fitwidth_script}", '
                    f'"{addon_dir}", '
                    f'"{selected_comic}")'
                )

                monitor = xbmc.Monitor()
                aborted = False

                try:
                    # Wait until the first image is displayed, or the reader
                    # finishes before becoming ready.
                    while (
                        bg_window.getProperty('fitwidth_ready') != 'true'
                        and bg_window.getProperty('fitwidth_done') != 'true'
                    ):
                        if monitor.abortRequested():
                            aborted = True
                            break
                        xbmc.sleep(100)
                finally:
                    # Close the dialogue as soon as loading has finished.
                    progress.close()

                if (
                    not aborted
                    and bg_window.getProperty('fitwidth_done') == 'true'
                    and bg_window.getProperty('fitwidth_ready') != 'true'
                ):
                    xbmc.log(
                        'FitWidth reader finished before becoming ready',
                        xbmc.LOGERROR
                    )

                if aborted or monitor.abortRequested():
                    return

                # Keep the library waiting until the reader itself closes.
                while bg_window.getProperty('fitwidth_done') != 'true':
                    if monitor.abortRequested():
                        return
                    xbmc.sleep(100)

                        #continue
                    
        elif result == 'settings':
            while True:
                settings_window = SettingsWindow(
                    'settings.xml',
                    addon_dir,
                    'default'
                )
                settings_window.addon_profile = addon_profile
                settings_window.settings_manager = settings_manager
                settings_window.theme_changed = False

                settings_window.doModal()

                theme_changed = settings_window.theme_changed
                del settings_window

                if theme_changed:
                    xbmc.log('Theme changed; reloading KODI skin', xbmc.LOGINFO)
                    xbmc.executebuiltin('ReloadSkin()')
                    xbmc.sleep(1000)

                if not theme_changed:
                    break


        elif result == 'load_content':
            addon_path = xbmcvfs.translatePath(addon.getAddonInfo('path'))
            fitwidth_script = os.path.join(addon_path, 'FitWidthImageViewer.py')
            current_window_id = xbmcgui.getCurrentWindowId()
            bg_window = xbmcgui.Window(10000)
            bg_window.setProperty('fitwidth_return_window', str(current_window_id))
            bg_window.setProperty('fitwidth_done', 'false')
            home_window.close()
            xbmc.executebuiltin(f'RunScript({fitwidth_script}, "{addon_path}")')
            print("DEBUG: About to enter load content window return polling loop") 
            while xbmcgui.Window(10000).getProperty('fitwidth_done') != 'true':
                    xbmc.sleep(100)
            return_window_id = int(xbmcgui.Window(10000).getProperty('fitwidth_return_window'))
            xbmc.executebuiltin(f'ActivateWindow({return_window_id})')
            break

    


if __name__ == '__main__':
    main()
