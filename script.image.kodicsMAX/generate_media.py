from PIL import Image, ImageDraw
import os

media_dir = 'resources/media'
os.makedirs(media_dir, exist_ok=True)

# Simple background (dark)
bg = Image.new('RGB', (1920, 1080), color=(20, 20, 30))
bg.save(f'{media_dir}/background.png')

# Folder icon
folder = Image.new('RGB', (200, 300), color=(100, 100, 150))
draw = ImageDraw.Draw(folder)
draw.rectangle([10, 10, 190, 290], outline=(200, 200, 200), width=3)
folder.save(f'{media_dir}/folder.png')

# No cover placeholder
no_cover = Image.new('RGB', (200, 300), color=(60, 60, 60))
draw = ImageDraw.Draw(no_cover)
draw.text((50, 140), 'No Cover', fill=(150, 150, 150))
no_cover.save(f'{media_dir}/no_cover.png')

# Green checkmark
checkmark = Image.new('RGBA', (35, 35), color=(0, 0, 0, 0))
draw = ImageDraw.Draw(checkmark)
draw.ellipse([0, 0, 34, 34], fill=(0, 200, 0))
draw.text((8, 6), '✓', fill=(255, 255, 255))
checkmark.save(f'{media_dir}/checkmark.png')

# Border
border = Image.new('RGBA', (210, 310), color=(0, 0, 0, 0))
draw = ImageDraw.Draw(border)
draw.rectangle([0, 0, 209, 309], outline=(150, 150, 150), width=5)
border.save(f'{media_dir}/border.png')

# Focused border
border_focused = Image.new('RGBA', (210, 310), color=(0, 0, 0, 0))
draw = ImageDraw.Draw(border_focused)
draw.rectangle([0, 0, 209, 309], outline=(255, 255, 0), width=5)
border_focused.save(f'{media_dir}/border_focused.png')

# Scrollbar assets
scrollbar_bg = Image.new('RGB', (20, 800), color=(40, 40, 40))
scrollbar_bg.save(f'{media_dir}/scrollbar_bg.png')

scrollbar_bar = Image.new('RGB', (20, 100), color=(150, 150, 150))
scrollbar_bar.save(f'{media_dir}/scrollbar_bar.png')

scrollbar_arrow = Image.new('RGB', (20, 20), color=(150, 150, 150))
scrollbar_arrow.save(f'{media_dir}/scrollbar_arrow.png')

print("Media files generated successfully!")

