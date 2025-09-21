#!/bin/bash
# Linux-optimized build script for Mirror Test executable

set -e

echo "Mirror Test - Linux Executable Builder"
echo "======================================"

# Check if we're on Linux
if [[ "$OSTYPE" != "linux-gnu"* ]]; then
    echo "Error: This script is designed for Linux systems only"
    echo "Current OS: $OSTYPE"
    exit 1
fi

# Check if Python 3 is available
if ! command -v python3 &> /dev/null; then
    echo "Error: Python 3 is required but not installed"
    exit 1
fi

# Check if pip is available
if ! command -v pip3 &> /dev/null; then
    echo "Error: pip3 is required but not installed"
    exit 1
fi

echo "✓ Linux system detected"
echo "✓ Python 3 available: $(python3 --version)"
echo "✓ pip3 available: $(pip3 --version)"

# Install PyInstaller if not already installed
if ! python3 -c "import PyInstaller" 2>/dev/null; then
    echo "Installing PyInstaller..."
    pip3 install pyinstaller
    echo "✓ PyInstaller installed"
else
    echo "✓ PyInstaller already installed"
fi

# Note: UPX compression removed for better compatibility and security

# Clean previous builds
echo "Cleaning previous builds..."
rm -rf build/ dist/ *.spec
echo "✓ Cleaned previous builds"

# Create optimized spec file
echo "Creating Linux-optimized spec file..."
cat > mirror-test.spec << 'EOF'
# -*- mode: python ; coding: utf-8 -*-
# Linux-optimized PyInstaller spec for Mirror Test

block_cipher = None

a = Analysis(
    ['main.py'],
    pathex=[],
    binaries=[],
    datas=[
        ('README.md', '.'),
        ('requirements.txt', '.'),
        ('bash-autocomplete.sh', '.'),
        ('full-config-example.yaml', '.'),
        ('server-config-example.yaml', '.'),
    ],
    hiddenimports=[
        'yaml',
        'flask',
        'flask_limiter',
        'flask_wtf',
        'flask_cors',
        'ldap',
        'werkzeug',
        'jinja2',
        'markupsafe',
        'itsdangerous',
        'click',
        'blinker',
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'tkinter',
        'matplotlib',
        'numpy',
        'pandas',
        'scipy',
        'PIL',
        'cv2',
        'PyQt5',
        'PyQt6',
        'PySide2',
        'PySide6',
        'wx',
        'gtk',
    ],
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name='mirror-test',
    debug=False,
    bootloader_ignore_signals=False,
    strip=True,  # Strip debug symbols for smaller binary
    runtime_tmpdir=None,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
EOF

echo "✓ Created Linux-optimized spec file"

# Build the executable
echo "Building executable with PyInstaller..."
python3 -m PyInstaller mirror-test.spec

if [ $? -eq 0 ]; then
    echo "✓ Build completed successfully"
else
    echo "✗ Build failed"
    exit 1
fi

# Test the executable
echo "Testing executable..."
if [ -f "dist/mirror-test" ]; then
    echo "✓ Executable created: dist/mirror-test"
elif [ -f "dist/mirror-test.exe" ]; then
    echo "⚠ Found .exe extension, renaming for Linux compatibility..."
    mv dist/mirror-test.exe dist/mirror-test
    echo "✓ Renamed to Linux format"
else
    echo "✗ Executable not found"
    exit 1
fi

# Test help command
if ./dist/mirror-test --help > /dev/null 2>&1; then
    echo "✓ Executable test passed"
else
    echo "✗ Executable test failed"
    exit 1
fi

# Get file size
SIZE=$(du -h dist/mirror-test | cut -f1)
echo "✓ Executable size: $SIZE"

# Make executable
chmod +x dist/mirror-test
echo "✓ Made executable"

echo ""
echo "======================================"
echo "✓ Linux build completed successfully!"
echo ""
echo "Executable location: dist/mirror-test"
echo "File size: $SIZE"
echo ""
echo "The executable is statically linked and should work on any Linux system."
echo "You can now distribute this single binary file."
echo ""
echo "Usage:"
echo "  ./dist/mirror-test --help"
echo "  ./dist/mirror-test list"
echo "  ./dist/mirror-test gui"
echo ""
