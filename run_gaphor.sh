#!/bin/bash

# Set up Poetry path
export PATH="/Users/rishiraj/Library/Python/3.12/bin:$PATH"

# Set library paths for macOS using native arm64 Homebrew libraries
export DYLD_FALLBACK_LIBRARY_PATH="/opt/homebrew/opt/glib/lib:/opt/homebrew/opt/libffi/lib:/opt/homebrew/opt/gtk4/lib:/opt/homebrew/opt/pango/lib:/opt/homebrew/opt/cairo/lib:/opt/homebrew/lib:/usr/local/lib:/usr/lib"
export DYLD_LIBRARY_PATH="/opt/homebrew/opt/glib/lib:/opt/homebrew/opt/libffi/lib:/opt/homebrew/opt/gtk4/lib:/opt/homebrew/opt/pango/lib:/opt/homebrew/opt/cairo/lib:$DYLD_LIBRARY_PATH"

# Set GObject Introspection paths
export GI_TYPELIB_PATH="/opt/homebrew/lib/girepository-1.0:/opt/homebrew/opt/gtk4/lib/girepository-1.0:/opt/homebrew/opt/glib/lib/girepository-1.0:/opt/homebrew/opt/pango/lib/girepository-1.0"
export GOBJECT_INTROSPECTION_LIBDIR="/opt/homebrew/opt/glib/lib"

# Set pkg-config path
export PKG_CONFIG_PATH="/opt/homebrew/opt/glib/lib/pkgconfig:/opt/homebrew/opt/libffi/lib/pkgconfig:/opt/homebrew/opt/gtk4/lib/pkgconfig"

# Change to project directory
cd /Users/rishiraj/Downloads/gaphor

# Run natively on arm64 with native libraries
exec poetry run python -m gaphor "$@"
