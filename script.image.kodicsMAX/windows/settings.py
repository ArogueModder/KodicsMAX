# -*- coding: utf-8 -*-
import os
import xbmc
import xbmcgui
import xbmcaddon
import xbmcvfs
import json

from urllib.parse import unquote

from lib.comic_library import LibraryManager


class SettingsWindow(xbmcgui.WindowXMLDialog):
    """Settings window for configuration."""
    THEME_IMAGE_CONTROLS = {
        307: 'background3.png',
        308: 'settings.png',
        309: 'LBD.png',
        310: 'TC.png',
        311: 'RH.png',
    }
    
    def __init__(self, xml_file, addon_path, default_skin):
        super().__init__(xml_file, addon_path, default_skin)
        #Set by Default.py 
        self.setup_theme_paths()
        self.addon_profile = None
        self.settings_manager = None
        self.library_manager = None


    def refresh_theme_images(self):
        for control_id, filename in self.THEME_IMAGE_CONTROLS.items():
            image_path = os.path.join(self.media_dir, filename)

            if not xbmcvfs.exists(image_path):
                xbmc.log(
                    'Theme image not found: {}'.format(image_path),
                    xbmc.LOGWARNING
                )
                continue

            self.getControl(control_id).setImage(image_path, False)

    def onInit(self):
        # Initialize library manager now that addon_profile is set
        if self.addon_profile and not self.library_manager:
            self.library_manager = LibraryManager(self.addon_profile)

        self.update_display()
        self.refresh_theme_images()
        xbmc.log('SettingsWindow initialized', xbmc.LOGINFO)
        

    def onClick(self, control_id):
        if control_id == 301:
            dialog = xbmcgui.Dialog()

            current_dir = self.settings_manager.get_setting(
                'library_base_dir',
                ''
            )

            directory = dialog.browse(
                0,
                'Select Library Base Directory',
                'files',
                '',
                False,
                False,
                current_dir
            )

            if directory:
                self.settings_manager.set_setting(
                    'library_base_dir',
                    directory
                )
                self.update_display()
        
        elif control_id == 302:  # Clear Thumbnail Cache button
            self.clear_cache()
        
        elif control_id == 303:  # Clear Read History button
            self.clear_history()
        
        elif control_id == 304:  # Back button
            self.close()

        elif control_id == 305:  # Choose Theme
            self.choose_theme()

        elif control_id == 306:  # Import Custom Theme
            self.import_theme()


    def onAction(self, action):
        if action.getId() in (9, 10, 92):  # Back, Escape, Backspace
            self.close()

    def update_display(self):
        """Update the displayed settings."""
        base_dir = self.settings_manager.get_setting('library_base_dir', '')
        label_control = self.getControl(301)
        if label_control:
            label_control.setLabel(base_dir if base_dir else 'Not Set - Click to Choose')

        theme_name = self.settings_manager.get_setting(
            'library_theme',
            ''
        )
        theme_control = self.getControl(305)
        theme_control.setLabel(
            'Theme: ' + theme_name if theme_name else 'Choose Theme'
        )



    def clear_cache(self):
        """Clear thumbnail cache."""
        self.library_manager.extractor.clear_cache()
        dialog = xbmcgui.Dialog()
        dialog.notification('KodicsMAX', 'Thumbnail cache cleared')

    def clear_history(self):
        """Clear read history."""
        history_file = self.library_manager.read_tracker.read_history_file
        if os.path.exists(history_file):
            os.remove(history_file)
            self.library_manager.read_tracker.read_history = {}
        dialog = xbmcgui.Dialog()
        dialog.notification('KodicsMAX', 'Read history cleared')


    #Theme Stuff
    def setup_theme_paths(self):
        """Set up bundled, custom, and active media paths."""
        addon = xbmcaddon.Addon()

        addon_path = xbmcvfs.translatePath(
            addon.getAddonInfo('path')
        )
        profile_path = xbmcvfs.translatePath(
            addon.getAddonInfo('profile')
        )

        self.bundled_themes_dir = os.path.join(
            addon_path, 'resources', 'libraryThemes'
        ).replace('\\', '/') + '/'

        self.custom_themes_dir = os.path.join(
            profile_path, 'libraryThemes'
        ).replace('\\', '/') + '/'

        self.media_dir = os.path.join(
            addon_path, 'resources', 'media'
        ).replace('\\', '/') + '/'

        xbmcvfs.mkdirs(self.custom_themes_dir)

    @staticmethod
    def join_vfs(folder, name):
        return folder.rstrip('/\\') + '/' + name

    def get_theme_names(self):
        """Return folder names from both bundled and custom theme folders."""
        names = set()

        for root in (self.bundled_themes_dir, self.custom_themes_dir):
            if xbmcvfs.exists(root):
                directories, _ = xbmcvfs.listdir(root)
                names.update(directories)

        return sorted(names, key=str.lower)

    def copy_folder_contents(self, source, destination, invalidate_cache=False):
        """Recursively copy a theme folder, logging the exact failure."""
        destination_dir = destination.rstrip('/\\')

        try:
            os.makedirs(destination_dir, exist_ok=True)
        except OSError as exc:
            xbmc.log(
                'Theme import: cannot create {!r}: {} (errno={})'.format(
                    destination_dir, exc, exc.errno
                ),
                xbmc.LOGERROR
            )
            return False

        if not os.path.isdir(destination_dir):
            xbmc.log(
                'Theme import: destination is not a directory: {!r}'.format(
                    destination_dir
                ),
                xbmc.LOGERROR
            )
            return False

        try:
            directories, files = xbmcvfs.listdir(source)


            directories, files = xbmcvfs.listdir(source)

            for directory in directories:
                child_source = self.join_vfs(source, directory)
                child_destination = self.join_vfs(destination, directory)

                if not self.copy_folder_contents(
                        child_source, child_destination, invalidate_cache):
                    return False

            for filename in files:
                source_file = self.join_vfs(source, filename)
                destination_file = self.join_vfs(destination, filename)

                if not xbmcvfs.copy(source_file, destination_file):
                    xbmc.log(
                        'Theme import: copy failed: {} -> {}'.format(
                            source_file, destination_file
                        ),
                        xbmc.LOGERROR
                    )
                    return False

                if invalidate_cache:
                    try:
                        self.remove_cached_texture(destination_file)
                    except Exception as exc:
                        xbmc.log(
                            'Theme copied, but texture cache removal failed for '
                            '{}: {}'.format(destination_file, exc),
                            xbmc.LOGWARNING
                        )

            return True

        except Exception as exc:
            xbmc.log(
                'Theme import failed while reading {} or writing {}: {}'.format(
                    source, destination, exc
                ),
                xbmc.LOGERROR
            )
            return False

    @staticmethod
    def texture_path_key(path):
        path = str(path).rstrip('/')

        if path.startswith('image://'):
            path = unquote(path[len('image://'):])
        elif path.startswith('file://'):
            path = unquote(path[len('file://'):])

        if path.startswith('special://'):
            path = xbmcvfs.translatePath(path)

        return os.path.normcase(os.path.normpath(path)).replace('\\', '/')
    
    
    def remove_cached_texture(self, source_url):
        target = self.texture_path_key(source_url)

        request = {
            "jsonrpc": "2.0",
            "method": "Textures.GetTextures",
            "params": {"properties": ["url"]},
            "id": 1
        }
        result = json.loads(xbmc.executeJSONRPC(json.dumps(request)))

        if "error" in result:
            xbmc.log("GetTextures failed: {}".format(result["error"]), xbmc.LOGWARNING)
            return

        for texture in result.get("result", {}).get("textures", []):
            texture_url = texture.get("url", '')
            xbmc.log("Texture URL from Kodi: {}".format(texture_url), xbmc.LOGDEBUG)

            if self.texture_path_key(texture_url) == target:
                remove_request = {
                    "jsonrpc": "2.0",
                    "method": "Textures.RemoveTexture",
                    "params": {"textureid": texture["textureid"]},
                    "id": 2
                }
                xbmc.executeJSONRPC(json.dumps(remove_request))

    def choose_theme(self):
        names = self.get_theme_names()
        if not names:
            xbmcgui.Dialog().ok('KodicsMAX', 'No themes found.')
            return

        selected = xbmcgui.Dialog().select('Select Theme', names)
        if selected < 0:  # The user cancelled.
            return

        name = names[selected]

        # Prefer the profile copy if one exists; otherwise use the bundled one.
        candidates = (
            self.join_vfs(self.custom_themes_dir, name),
            self.join_vfs(self.bundled_themes_dir, name)
        )
        source = next(
            (path for path in candidates if xbmcvfs.exists(path + '/')),
            None
        )

        if not source or not self.copy_folder_contents(
            source, self.media_dir, invalidate_cache=True
        ):
            xbmcgui.Dialog().ok(
                'KodicsMAX', 'Could not apply the selected theme.'
            )
            return

        self.settings_manager.set_setting('library_theme', name)
        self.theme_changed = True
        xbmcgui.Dialog().notification(
            'KodicsMAX', 'Theme applied: ' + name
        )
        #self.clear_all_kodi_texture_cache()
        self.close()

    def import_theme(self):
        source = xbmcgui.Dialog().browse(
            0,
            'Select Custom Theme Folder',
            'files',
            '',
            False,
            True
        )
        if not source:
            return

        name = source.rstrip('/\\').replace('\\', '/').split('/')[-1]
        if not name or name in ('.', '..'):
            xbmcgui.Dialog().ok(
                'KodicsMAX', 'That folder name cannot be used.'
            )
            return

        # Avoid ambiguous duplicates between bundled and imported themes.
        if name in self.get_theme_names():
            xbmcgui.Dialog().ok(
                'KodicsMAX',
                'A theme with that name already exists.'
            )
            return

        destination = self.join_vfs(self.custom_themes_dir, name)

        if not self.copy_folder_contents(source, destination):
            xbmcgui.Dialog().ok(
                'KodicsMAX', 'Could not import the theme folder.'
            )
            return

        self.update_display()
        xbmcgui.Dialog().notification(
            'KodicsMAX', 'Theme imported: ' + name
        )

    def _texture_rpc(self, method, params, request_id):
        request = {
            'jsonrpc': '2.0',
            'method': method,
            'params': params,
            'id': request_id
        }

        raw = xbmc.executeJSONRPC(json.dumps(request))
        response = json.loads(raw)

        if 'error' in response:
            raise RuntimeError('{} failed: {}'.format(method, response['error']))

        return response.get('result', {})


    def clear_all_kodi_texture_cache(self):
        result = self._texture_rpc(
            'Textures.GetTextures', {}, 1)
        
        textures = result.get('textures')

        if textures is None:
            raise RuntimeError('Textures.GetTextures returned no texture list')

        progress = xbmcgui.DialogProgress()
        progress.create('Theme', 'Clearing Kodi texture cache…')

        removed = 0
        failed = 0

        try:
            total = len(textures)

            for index, texture in enumerate(textures):
                if progress.iscanceled():
                    break

                texture_id = texture.get('textureid')
                try:
                    self._texture_rpc(
                        'Textures.RemoveTexture',
                        {'textureid': texture_id},
                        index + 2
                    )
                    removed += 1
                except Exception as exc:
                    failed += 1
                    xbmc.log(
                        'Could not remove texture {} ({}): {}'.format(
                            texture_id, texture.get('url', ''), exc
                        ),
                        xbmc.LOGWARNING
                    )

                if index % 10 == 0 or index == total - 1:
                    percent = int((index + 1) * 100 / max(total, 1))
                    progress.update(percent, 'Removing cached textures…')

        finally:
            progress.close()

        xbmc.log(
            'Texture cache clear finished: removed {}, failed {}, total {}'.format(
                removed, failed, len(textures)
            ),
            xbmc.LOGINFO
        )

        return removed, failed
