# -------------------------------------------------------------------------
#     Copyright (C) 2005-2013 Martin Strohalm <www.mmass.org>

#     This program is free software; you can redistribute it and/or modify
#     it under the terms of the GNU General Public License as published by
#     the Free Software Foundation; either version 3 of the License, or
#     (at your option) any later version.

#     This program is distributed in the hope that it will be useful,
#     but WITHOUT ANY WARRANTY; without even the implied warranty of
#     MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
#     GNU General Public License for more details.

#     Complete text of GNU GPL can be found in the file LICENSE.TXT in the
#     main directory of the program.
# -------------------------------------------------------------------------


# load objects
from . import plot_canvas as _plot_canvas
from . import plot_objects as _plot_objects

_plot_objects_names = getattr(_plot_objects, "__all__", None)
if _plot_objects_names is None:
    _plot_objects_names = [name for name in dir(_plot_objects) if not name.startswith("_")]

_plot_canvas_names = getattr(_plot_canvas, "__all__", None)
if _plot_canvas_names is None:
    _plot_canvas_names = [name for name in dir(_plot_canvas) if not name.startswith("_")]

for _name in _plot_objects_names:
    globals()[_name] = getattr(_plot_objects, _name)

for _name in _plot_canvas_names:
    globals()[_name] = getattr(_plot_canvas, _name)

__all__ = [*_plot_objects_names, *_plot_canvas_names]  # pyright: ignore[reportUnsupportedDunderAll]

del _name
del _plot_objects_names
del _plot_canvas_names
