import os
import sys
import json
import zipfile
import shutil
import platform
from datetime import datetime
import xbmc
import xbmcvfs
import xbmcgui
import traceback
from PIL import Image

LANCZOS = getattr(Image, "Resampling", Image).LANCZOS


from io import BytesIO
import tempfile

lib_dir = os.path.dirname(
    os.path.abspath(__file__)
)

if lib_dir not in sys.path:
    sys.path.insert(0, lib_dir)

import rarfile

#Helpers for Android/ios/TVos
def _translate_kodi_path(path):
    if not path.startswith("special://"):
        return path

    try:
        return xbmcvfs.translatePath(path)
    except AttributeError:
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



class ComicExtractor:
    """Extracts metadata and thumbnails from CBR/CBZ files."""
    
    def __init__(self, addon_profile):
        self.addon_profile = _translate_kodi_path(addon_profile)
        self.thumbnail_cache_dir = os.path.join(
            self.addon_profile, "thumbnails"
        )
        os.makedirs(self.thumbnail_cache_dir, exist_ok=True)
        self._configure_rarfile()

    def _get_mobile_temp_dir(self):
        temp_dir = os.path.join(self.addon_profile, "temp", "library")
        os.makedirs(temp_dir, exist_ok=True)

        xbmc.log(
            f"KodicsMAX: CBR temp directory: {temp_dir}",
            xbmc.LOGINFO,
        )

        probe_path = os.path.join(temp_dir, ".write_test")
        try:
            with open(probe_path, "wb") as probe:
                probe.write(b"ok")
        except Exception:
            xbmc.log(
                "KodicsMAX: Cannot write to CBR temp directory "
                f"{temp_dir}:\n{traceback.format_exc()}",
                xbmc.LOGERROR,
            )
            raise
        finally:
            try:
                if os.path.exists(probe_path):
                    os.remove(probe_path)
            except OSError:
                pass

        tempfile.tempdir = temp_dir

        xbmc.log(
            f"KodicsMAX: Python default temp directory: "
            f"{tempfile.gettempdir()}",
            xbmc.LOGINFO,
        )
        
        return temp_dir

    def _configure_rarfile(self):
        """Configure rarfile to use the addon's bundled unrar binary."""
        machine = platform.machine().lower()

        if machine in ('aarch64', 'arm64'):
            architecture = 'aarch64'
        else:
            architecture = 'x86_64'

        unrar_path = os.path.join(
            os.path.dirname(
                os.path.dirname(os.path.abspath(__file__))
            ),
            'bin',
            architecture,
            'unrar'
        )

        if not os.path.isfile(unrar_path):
            xbmc.log(
                f'KodicsMAX: Bundled unrar not found: {unrar_path}',
                xbmc.LOGERROR
            )
            return False

        try:
            if os.name != 'nt':
                os.chmod(unrar_path, 0o755)

            rarfile.UNRAR_TOOL = unrar_path

            xbmc.log(
                f'KodicsMAX: Configured unrar: {unrar_path}',
                xbmc.LOGINFO
            )
            return True

        except OSError as error:
            xbmc.log(
                f'KodicsMAX: Could not configure unrar at {unrar_path}: {error}',
                xbmc.LOGERROR
            )
            return False



    
    def get_thumbnail(self, comic_path, thumbnail_width=200):
        """
        Extract first image from CBR/CBZ and cache as thumbnail.
        Returns path to cached thumbnail.
        """
        cache_filename = self._get_cache_filename(comic_path)
        cache_path = os.path.join(self.thumbnail_cache_dir, cache_filename)
        
        # Return cached thumbnail if it exists
        if os.path.exists(cache_path):
            return cache_path
        
        try:
            first_image = self._extract_first_image(comic_path)
            if first_image:
                xbmc.log(
                    f'KodicsMAX: First image extracted from: {comic_path}',
                    xbmc.LOGINFO
                )

                thumbnail = self._resize_image(
                    first_image,
                    thumbnail_width
                )

                thumbnail.save(cache_path, 'PNG')

                xbmc.log(
                    f'KodicsMAX: Thumbnail cached at: {cache_path}',
                    xbmc.LOGINFO
                )

                return cache_path

            xbmc.log(
                f'KodicsMAX: No thumbnail image extracted from: {comic_path}',
                xbmc.LOGWARNING
            )

        except Exception as e:
            xbmc.log(f"Error extracting thumbnail from {comic_path}: {str(e)}", xbmc.LOGERROR)
        
        return None
    
    def _extract_first_image(self, comic_path):
        """Extract the first image file from CBR/CBZ archive."""
        try:
            # CBZ files are ZIP archives
            if comic_path.lower().endswith('.cbz'):
                with zipfile.ZipFile(comic_path, 'r') as zip_ref:
                    file_list = sorted(zip_ref.namelist())
                    for file in file_list:
                        if file.lower().endswith(('.jpg', '.jpeg', '.png', '.gif', '.webp')):
                            image_data = zip_ref.read(file)
                            return Image.open(BytesIO(image_data))
            
            # CBR files are RAR archives - use a temporary approach
            elif comic_path.lower().endswith('.cbr'):
                # For RAR, we'll try using patool or unrar if available
                # For now, return None - we'll handle this below
                return self._extract_cbr_fallback(comic_path)
        
        except Exception as e:
            xbmc.log(f"Error reading archive {comic_path}: {str(e)}", xbmc.LOGERROR)
        
        return None
    
    def _extract_cbr_fallback(self, cbr_path):
        image_extensions = ('.jpg', '.jpeg', '.png', '.gif', '.webp')

        try:
            temp_parent = (
            self._get_mobile_temp_dir()
            if _is_sandboxed_platform()
            else None
            )
            
            with tempfile.TemporaryDirectory(prefix='kodicsmax_cover_', dir=temp_parent,) as temp_dir:
                with rarfile.RarFile(cbr_path, 'r') as archive:
                    image_names = sorted(
                        name for name in archive.namelist()
                        if name.lower().endswith(image_extensions)
                    )

                    if not image_names:
                        xbmc.log(
                            f'KodicsMAX: No images found in CBR: {cbr_path}',
                            xbmc.LOGWARNING
                        )
                        return None

                    first_image_name = image_names[0]
                    xbmc.log(
                        f'KodicsMAX: Extracting CBR cover: {first_image_name}',
                        xbmc.LOGINFO
                    )

                    extracted_path = archive.extract(
                        first_image_name,
                        path=temp_dir
                    )

                with Image.open(extracted_path) as image:
                    image.load()
                    return image.copy()

        except Exception as error:
            xbmc.log(
                f"KodicsMAX: CBR extraction failed for {cbr_path}:\n",
                f"{traceback.format_exc()}",
                xbmc.LOGERROR
            )
            return None

    
    def _resize_image(self, image, target_width):
        """Resize image maintaining aspect ratio."""
        ratio = target_width / float(image.width)
        new_height = int(float(image.height) * float(ratio))
        resampling = getattr(Image, "Resampling", Image)
        return image.resize((target_width, new_height), resampling.LANCZOS)
    
    def _get_cache_filename(self, comic_path):
        """Generate cache filename from comic path."""
        import hashlib
        path_hash = hashlib.md5(comic_path.encode()).hexdigest()
        return f"{path_hash}.png"
    
    def clear_cache(self):
        """Clear all cached thumbnails."""
        try:
            if os.path.exists(self.thumbnail_cache_dir):
                shutil.rmtree(self.thumbnail_cache_dir)
                os.makedirs(self.thumbnail_cache_dir)
        except Exception as e:
            xbmc.log(f"Error clearing thumbnail cache: {str(e)}", xbmc.LOGERROR)


class ReadTracker:
    """Tracks read status of comics with persistent JSON storage."""
    
    def __init__(self, addon_profile):
        self.addon_profile = addon_profile
        self.read_history_file = os.path.join(addon_profile, 'read_history.json')
        self.read_history = self._load_history()
    
    def update_progress(self, comic_path, current_page, total_pages):
        """Save the reader's current 1-based page and total page count."""
        if not comic_path or total_pages <= 0:
            return

        total_pages = int(total_pages)
        current_page = max(1, min(int(current_page), total_pages))
        progress = current_page / total_pages * 100

        record = self.read_history.get(comic_path, {})
        record.update({
            'current_page': current_page,
            'total_pages': total_pages,
            'read': progress >= 96,
            'updated_at': datetime.now().isoformat(),
        })

        # Preserve a completion timestamp for compatibility with get_read_time().
        if progress >= 96 and not record.get('timestamp'):
            record['timestamp'] = datetime.now().isoformat()

        self.read_history[comic_path] = record
        self._save_history()


    def get_progress(self, comic_path):
        """Return saved page progress, or None if no page progress exists."""
        record = self.read_history.get(comic_path, {})
        current_page = record.get('current_page')
        total_pages = record.get('total_pages')

        if current_page is None or not total_pages:
            return None

        return {
            'current_page': current_page,
            'total_pages': total_pages,
        }


    def get_read_status(self, comic_path):
        """Return 'complete', 'in_progress', or '' for the thumbnail badge."""
        record = self.read_history.get(comic_path, {})

        # Support older entries created by mark_read(), which have no page counts.
        if record.get('read', False):
            return 'complete'

        current_page = record.get('current_page')
        total_pages = record.get('total_pages')
        if current_page is None or not total_pages:
            return ''

        progress = current_page / total_pages * 100
        if progress >= 96:
            return 'complete'
        if progress > 4:
            return 'in_progress'
        return ''

        
        
    
    
    
    def _load_history(self):
        """Load read history from JSON file."""
        if os.path.exists(self.read_history_file):
            try:
                with open(self.read_history_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                xbmc.log(f"Error loading read history: {str(e)}", xbmc.LOGERROR)
        return {}
    
    def _save_history(self):
        """Save read history to JSON file."""
        try:
            with open(self.read_history_file, 'w') as f:
                json.dump(self.read_history, f, indent=2)
        except Exception as e:
            xbmc.log(f"Error saving read history: {str(e)}", xbmc.LOGERROR)
    
    def mark_read(self, comic_path):
        """Mark a comic as read with timestamp."""
        self.read_history[comic_path] = {
            'read': True,
            'timestamp': datetime.now().isoformat()
        }
        self._save_history()
    
    def mark_unread(self, comic_path):
        """Mark a comic as unread."""
        if comic_path in self.read_history:
            del self.read_history[comic_path]
            self._save_history()
    
    def is_read(self, comic_path):
        """Check if a comic has been read."""
        return comic_path in self.read_history and self.read_history[comic_path].get('read', False)
    
    def get_read_time(self, comic_path):
        """Get the timestamp when a comic was read."""
        if comic_path in self.read_history:
            return self.read_history[comic_path].get('timestamp')
        return None


class LibraryManager:
    """Scans and indexes comic library from base directory."""
    
    def __init__(self, addon_profile):
        self.addon_profile = addon_profile
        self.extractor = ComicExtractor(addon_profile)
        self.read_tracker = ReadTracker(xbmcvfs.translatePath(addon_profile))
        self.base_directory = None
    
    def set_base_directory(self, directory):
        """Set the base directory for the comic library."""
        if os.path.isdir(directory):
            self.base_directory = directory
            return True
        return False
    
    def get_library_items(self, directory=None):
        """Get all items (folders and comics) in a directory."""
        if directory is None:
            directory = self.base_directory

        if not directory or not os.path.isdir(directory):
            return []

        items = []
        progress = None

        try:
            entries = sorted(os.listdir(directory))
            total_comics = sum(
                1
                for item in entries
                if not item.startswith(".")
                and item.lower().endswith((".cbr", ".cbz"))
                and not os.path.isdir(os.path.join(directory, item))
            )

            if total_comics:
                progress = xbmcgui.DialogProgressBG()
                progress.create("Building Library", "Please wait...")

            processed = 0

            for item in entries:
                item_path = os.path.join(directory, item)

                # Skip hidden files and folders.
                if item.startswith("."):
                    continue

                if os.path.isdir(item_path):
                    items.append({
                        "type": "folder",
                        "name": item,
                        "path": item_path,
                        "thumbnail": None,
                        "is_read": False,
                    })

                elif item.lower().endswith((".cbr", ".cbz")):
                    thumbnail = self.extractor.get_thumbnail(item_path)
                    read_status = self.read_tracker.get_read_status(item_path)

                    items.append({
                        "type": "comic",
                        "name": os.path.splitext(item)[0],
                        "path": item_path,
                        "thumbnail": thumbnail,
                        "is_read": read_status == "complete",
                        "read_status": read_status,
                    })

                    processed += 1
                    progress.update(
                        int(processed * 100 / total_comics),
                        "Building Library",
                        f"Please wait... ({processed}/{total_comics})",
                    )

        except Exception as e:
            xbmc.log(
                f"Error scanning library directory {directory}: {str(e)}",
                xbmc.LOGERROR,
            )

        finally:
            if progress is not None:
                progress.close()

        return items


    def get_full_library(self, directory=None):
        """Get all comics recursively (flattened list, ignoring folder structure)."""
        if directory is None:
            directory = self.base_directory

        if not directory or not os.path.isdir(directory):
            return []

        comics = []
        progress = None

        try:
            # Gather paths first so the progress dialog can show a percentage.
            comic_paths = []

            for root, dirs, files in os.walk(directory):
                dirs[:] = [name for name in dirs if not name.startswith(".")]

                for file in sorted(files):
                    if not file.startswith(".") and file.lower().endswith(
                        (".cbr", ".cbz")
                    ):
                        comic_paths.append(os.path.join(root, file))

            total_comics = len(comic_paths)

            if total_comics:
                progress = xbmcgui.DialogProgressBG()
                progress.create("Building Library", "Please wait...")

            for processed, item_path in enumerate(comic_paths, start=1):
                thumbnail = self.extractor.get_thumbnail(item_path)
                read_status = self.read_tracker.get_read_status(item_path)

                comics.append({
                    "type": "comic",
                    "name": os.path.splitext(os.path.basename(item_path))[0],
                    "path": item_path,
                    "thumbnail": thumbnail,
                    "is_read": read_status == "complete",
                    "read_status": read_status,
                })

                progress.update(
                    int(processed * 100 / total_comics),
                    "Building Library",
                    f"Please wait... ({processed}/{total_comics})",
                )

        except Exception as e:
            xbmc.log(f"Error scanning library: {str(e)}", xbmc.LOGERROR)

        finally:
            if progress is not None:
                progress.close()

        return comics
