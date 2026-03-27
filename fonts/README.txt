# Fonts Directory

Place the following TrueType font files here:
- DejaVuSans.ttf
- DejaVuSans-Bold.ttf

## How to get them:

### On Raspberry Pi (automatic via setup.sh):
The setup.sh script will copy these from the system font directory automatically.

### On Windows (manual):
1. Download from: https://dejavu-fonts.github.io/Download.html
2. Extract the ZIP
3. Copy DejaVuSans.ttf and DejaVuSans-Bold.ttf to this folder

### Alternative — system fonts:
The app will fall back to PIL's default font if these files are missing,
but the OLED display will look less clean.
