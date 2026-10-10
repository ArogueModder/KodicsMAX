# -*- coding: utf-8 -*-

import os
import xbmc
import xbmcgui
import xbmcvfs

from lib.comic_library import LibraryManager


class LibraryWindow(xbmcgui.WindowXMLDialog):
    """Library browser window with grid display of comics and folders."""
    THEME_IMAGE_CONTROLS = {
        401: 'background3.png',
        402: 'Library.png',
        #403: 'readmark.png',
        #404: 'checkmark.png',
        405: 'flatbar.png',
    }
    
    
    def __init__(self, xml_file, addon_path, default_skin):
        super().__init__(xml_file, addon_path, default_skin)

        
        
        self.addon_path = addon_path
        self.addon_profile = None
        self.library_manager = None
        self.current_directory = None
        self.selected_item = None
        self.root_directory = None

        self.folder_icon = os.path.join(
            self.addon_path,
            'resources',
            'media',
            'folder.png'
        )

        self.no_cover_icon = os.path.join(
            self.addon_path,
            'resources',
            'media',
            'no_cover.png'
        )

        #footer icons
        self.folder_type_icon = os.path.join(
            self.addon_path, 'resources', 'media', 'foldericon.png'
        )
        self.cbr_type_icon = os.path.join(
            self.addon_path, 'resources', 'media', 'CBR.png'
        )
        self.cbz_type_icon = os.path.join(
            self.addon_path, 'resources', 'media', 'CBZ.png'
        )

        self.media_dir = os.path.join(
                    addon_path, 'resources', 'media'
                ).replace('\\', '/') + '/'
        

    def onInit(self):
        xbmc.log(
            'LibraryWindow.onInit started. Directory: {}'.format(
                self.current_directory
            ),
            xbmc.LOGINFO
        )

        self.refresh_theme_images()
        try:
            if self.addon_profile and not self.library_manager:
                self.library_manager = LibraryManager(
                    self.addon_profile
                )

            if not self.library_manager:
                raise RuntimeError(
                    'LibraryManager was not initialized'
                )

            xbmc.log(
                'LibraryManager initialized successfully',
                xbmc.LOGINFO
            )

            if self.current_directory:
                self.populate_grid()
            else:
                xbmc.log(
                    'LibraryWindow: no current directory was provided',
                    xbmc.LOGWARNING
                )

        except Exception as error:
            xbmc.log(
                'LibraryWindow.onInit error: {}'.format(error),
                xbmc.LOGERROR
            )

            xbmcgui.Dialog().ok(
                'Library Error',
                str(error)
            )

            self.close()

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


    def onClick(self, control_id):
        if control_id == 200:
            list_control = self.getControl(200)
            selected_item = list_control.getSelectedItem()

            if not selected_item:
                xbmc.log(
                    'LibraryWindow: no list item selected',
                    xbmc.LOGWARNING
                )
                return

            comic_path = selected_item.getProperty('comic_path')
            folder_path = selected_item.getProperty('folder_path')

            xbmc.log(
                'Selected item: {} | comic: {} | folder: {}'.format(
                    selected_item.getLabel(),
                    comic_path,
                    folder_path
                ),
                xbmc.LOGINFO
            )

            if folder_path:
                self.current_directory = folder_path
                self.populate_grid()

            elif comic_path:
                self.selected_item = comic_path

                xbmc.log(
                    'Comic selected: {}'.format(comic_path),
                    xbmc.LOGINFO
                )

                self.close()

        elif control_id == 201:
            self.go_back()

        elif control_id == 202:
            self.populate_grid()

    def onAction(self, action):
        if action.getId() in (9, 10, 92):
            self.go_back()

    def populate_grid(self):
        """Populate the grid with folders and comics."""

        try:
            if not self.current_directory:
                xbmc.log(
                    'LibraryWindow: current directory is empty',
                    xbmc.LOGWARNING
                )
                return

            xbmc.log(
                'Scanning library directory: {}'.format(
                    self.current_directory
                ),
                xbmc.LOGINFO
            )

            list_control = self.getControl(200)
            list_control.reset()

            items = self.library_manager.get_library_items(
                self.current_directory
            )

            if items is None:
                items = []

            # Show folders first; sort folders and comics alphabetically within each group.
            items = sorted(
                items,
                key=lambda item: (
                    0 if isinstance(item, dict) and item.get('type') == 'folder' else 1,
                    str(item.get('name', 'Unnamed')).lower()
                    if isinstance(item, dict) else ''
                )
            )

            xbmc.log(
                'Library returned {} items'.format(len(items)),
                xbmc.LOGINFO
            )


            for item in items:
                if not isinstance(item, dict):
                    xbmc.log(
                        'Skipping invalid library item: {}'.format(item),
                        xbmc.LOGWARNING
                    )
                    continue

                item_name = item.get('name', 'Unnamed')
                item_type = item.get('type', '')
                item_path = item.get('path', '')

                list_item = xbmcgui.ListItem(
                    label=item_name
                )

                #footer icons
                if item_type == 'folder':
                    type_icon = self.folder_type_icon
                else:
                    normalized_path = (item_path or item_name).replace('\\', '/')
                    extension = os.path.splitext(normalized_path)[1].lower()

                    type_icon = {
                        '.cbr': self.cbr_type_icon,
                        '.cbz': self.cbz_type_icon,
                    }.get(extension, '')

                list_item.setProperty('type_icon', type_icon)
                
                
                if item_type == 'folder':
                    list_item.setArt({
                        'thumb': self.folder_icon,
                        'icon': self.folder_icon
                    })

                    list_item.setProperty(
                        'folder_path',
                        item_path
                    )

                    xbmc.log(
                        'Added folder: {}'.format(item_path),
                        xbmc.LOGINFO
                    )

                else:
                    thumbnail = item.get('thumbnail') or ''

                    thumbnail_exists = False

                    if thumbnail:
                        try:
                            thumbnail_exists = xbmcvfs.exists(
                                thumbnail
                            )
                        except Exception as error:
                            xbmc.log(
                                'Could not check thumbnail {}: {}'.format(
                                    thumbnail,
                                    error
                                ),
                                xbmc.LOGWARNING
                            )

                    if thumbnail_exists:
                        artwork = thumbnail
                        xbmc.log(
                            'Using thumbnail for {}: {}'.format(
                                item_name,
                                thumbnail
                            ),
                            xbmc.LOGINFO
                        )
                    else:
                        artwork = self.no_cover_icon

                        xbmc.log(
                            'No valid thumbnail for {}. '
                            'Using fallback: {}'.format(
                                item_name,
                                self.no_cover_icon
                            ),
                            xbmc.LOGWARNING
                        )

                    list_item.setArt({
                        'thumb': artwork,
                        'icon': artwork
                    })

                    list_item.setProperty(
                        'comic_path',
                        item_path
                    )

                    read_status = item.get('read_status', '')
                    if not read_status and item.get('is_read', False):
                        read_status = 'complete'

                    list_item.setProperty('read_status', read_status)

                    if item.get('is_read', False):
                        list_item.setProperty(
                            'IsPlayed',
                            'true'
                        )

                    xbmc.log(
                        'Added comic: {} | path: {} | thumbnail: {}'.format(
                            item_name,
                            item_path,
                            artwork
                        ),
                        xbmc.LOGINFO
                    )

                list_control.addItem(list_item)

        except Exception as error:
            xbmc.log(
                'LibraryWindow.populate_grid error: {}'.format(error),
                xbmc.LOGERROR
            )

            xbmcgui.Dialog().ok(
                'Library Error',
                str(error)
            )

    def show(self, base_directory, start_directory=None):
        """Display the library window with the given base directory."""

        self.root_directory = self._normalize_directory(base_directory)

        if start_directory is None:
            start_directory = base_directory

        self.current_directory = self._normalize_directory(start_directory)

                
        self.selected_item = None

        self.doModal()

        return self.selected_item

    @staticmethod
    def _normalize_directory(path):
        if not path:
            return ''

        path = path.replace('\\', '/')

        # Preserve a Windows drive root such as C:/
        if len(path) == 3 and path[1] == ':' and path[2] == '/':
            return path

        while len(path) > 1 and path.endswith('/'):
            path = path[:-1]

        return path


    @staticmethod
    def _parent_directory(path):
        path = LibraryWindow._normalize_directory(path)

        if '/' not in path:
            return ''

        parent = path.rsplit('/', 1)[0]

        if not parent and path.startswith('/'):
            return '/'

        # Preserve a Windows drive root such as C:/
        if len(parent) == 2 and parent[1] == ':':
            return parent + '/'

        return parent


    def go_back(self):
        current = self._normalize_directory(self.current_directory)
        root = self._normalize_directory(self.root_directory)

        if not current or not root or current == root:
            self.close()
            return

        parent = self._parent_directory(current)

        if not parent or parent == current:
            self.close()
            return

        self.current_directory = parent
        self.populate_grid()

