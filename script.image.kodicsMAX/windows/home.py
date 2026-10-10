# -*- coding: utf-8 -*-
import xbmc
import xbmcgui
import os
import xbmcvfs


class HomeWindow(xbmcgui.WindowXMLDialog):
    THEME_IMAGE_CONTROLS = {
        106: 'background4.png',
        105: 'KodicsMAXtitle.png',
        #101: 'Library.png',
        #102: 'loadcontent.png',
        #103: 'settings.png',
        #104: 'exit.png',
    }
    
    
    def __init__(self, xml_file, addon_path, default_skin):
        super().__init__(xml_file, addon_path, default_skin)
        self.result = None

        self.media_dir = os.path.join(
                    addon_path, 'resources', 'media'
                ).replace('\\', '/') + '/'

    def onInit(self):
        xbmc.log('HomeWindow initialized', xbmc.LOGINFO)
        self.result = None

        self.refresh_theme_images()
        xbmc.log('SettingsWindow initialized', xbmc.LOGINFO)

    def onClick(self, control_id):
        mapping = {
            101: 'library',
            102: 'load_content',
            103: 'settings',
            104: 'exit',
        }
        if control_id in mapping:
            self.result = mapping[control_id]
            xbmc.log(f'HomeWindow: User selected {self.result}', xbmc.LOGINFO)
            self.close()

    def onAction(self, action):
        if action.getId() in (9, 10, 92):  # Back, Escape, Backspace
            self.result = 'exit'
            xbmc.log('HomeWindow: User pressed back', xbmc.LOGINFO)
            self.close()

    def show(self):
        self.doModal()
        return self.result

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
