#!/bin/bash

# Set up Poetry path (using Homebrew's poetry in /usr/local for Intel Mac)
export PATH="/usr/local/bin:$PATH"

# Set library paths for macOS using Intel Homebrew libraries (/usr/local)
export DYLD_FALLBACK_LIBRARY_PATH="/usr/local/opt/glib/lib:/usr/local/opt/libffi/lib:/usr/local/opt/gtk4/lib:/usr/local/opt/pango/lib:/usr/local/opt/cairo/lib:/usr/local/lib:/usr/lib"
export DYLD_LIBRARY_PATH="/usr/local/opt/glib/lib:/usr/local/opt/libffi/lib:/usr/local/opt/gtk4/lib:/usr/local/opt/pango/lib:/usr/local/opt/cairo/lib:$DYLD_LIBRARY_PATH"

# Set GObject Introspection paths
export GI_TYPELIB_PATH="/usr/local/lib/girepository-1.0:/usr/local/opt/gtk4/lib/girepository-1.0:/usr/local/opt/glib/lib/girepository-1.0:/usr/local/opt/pango/lib/girepository-1.0"
export GOBJECT_INTROSPECTION_LIBDIR="/usr/local/opt/glib/lib"

# Set pkg-config path
export PKG_CONFIG_PATH="/usr/local/opt/glib/lib/pkgconfig:/usr/local/opt/libffi/lib/pkgconfig:/usr/local/opt/gtk4/lib/pkgconfig"

# Change to project directory
cd /Users/rishiraj/Documents/Projects/gaphor-fork/gaphor

# Run natively on arm64 with native libraries
exec poetry run python -m gaphor "$@"
