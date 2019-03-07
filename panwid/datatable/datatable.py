import logging
logger = logging.getLogger("panwid.datable")
import urwid
import urwid_utils.palette
from ..listbox import ScrollingListBox
from orderedattrdict import OrderedDict
from collections.abc import MutableMapping
import itertools
import copy
import traceback
import math
from blist import blist
from dataclasses import *
import typing

from .dataframe import *
from .rows import *
from .columns import *
from .common import *


class DataTable(urwid.WidgetWrap, urwid.listbox.ListWalker):


    signals = ["select", "refresh", "focus", "blur",
               # "focus", "unfocus", "row_focus", "row_unfocus",
               "drag_start", "drag_continue", "drag_stop"]

    ATTR = "table"

    columns = []

    data = None

    limit = None
    index = "index"

    with_header = True
    with_footer = False
    with_scrollbar = False
    cell_selection = False

    sort_by = (None, None)
    query_sort = False
    sort_icons = True
    sort_refocus = False
    no_load_on_init = None

    border = DEFAULT_TABLE_BORDER
    padding = DEFAULT_CELL_PADDING


    detail_fn = None
    detail_selectable = False

    auto_expand_details = False
    ui_sort = True
    ui_resize = True
    row_attr_fn = None

    attr_map = {}
    focus_map = {}
    column_focus_map = {}
    highlight_map = {}
    highlight_focus_map = {}
    highlight_focus_map2 = {}

    def __init__(self,
                 columns = None,
                 data = None,
                 limit = None,
                 index = None,
                 with_header = None, with_footer = None, with_scrollbar = None,
                 cell_selection = None,
                 sort_by = None, query_sort = None, sort_icons = None,
                 sort_refocus = None,
                 no_load_on_init = None,
                 border = None, padding = None,
                 detail_fn = None, detail_selectable = None,
                 auto_expand_details = False,
                 ui_sort = None,
                 ui_resize = None,
                 row_attr_fn = None):

        self._focus = 0
        self.page = 0
        if columns is not None:
            self.columns = columns
        else:
            self.columns = [copy.deepcopy(c) for c in self.columns]

        if not self.columns:
            raise Exception("must define columns for data table")
        if index: self.index = index

        if not self.index in self.column_names:
            self.columns.insert(
                0,
                DataTableColumn(self.index, hide=True)
            )

        if data is not None:
            self.data = data

        if query_sort: self.query_sort = query_sort

        if sort_by:
            if isinstance(sort_by, tuple):
                column = sort_by[0]
                reverse = sort_by[1]
            else:
                column = sort_by
                reverse = None
                self.sort_by = (column, reverse)

            self.sort_by = (column, reverse)

        self.initial_sort = self.sort_by

        if sort_icons is not None: self.sort_icons = sort_icons
        if no_load_on_init is not None: self.no_load_on_init = no_load_on_init

        if with_header is not None: self.with_header = with_header
        if with_footer is not None: self.with_footer = with_footer
        if with_scrollbar is not None: self.with_scrollbar = with_scrollbar
        if cell_selection is not None: self.cell_selection = cell_selection
        if border is not None: self.border = border
        if padding is not None: self.padding = padding

        if ui_sort is not None: self.ui_sort = ui_sort
        if ui_resize is not None: self.ui_resize = ui_resize

        if row_attr_fn is not None: self.row_attr_fn = row_attr_fn

        if detail_fn is not None: self.detail_fn = detail_fn
        if detail_selectable is not None: self.detail_selectable = detail_selectable
        if auto_expand_details: self.auto_expand_details = auto_expand_details

        # self.offset = 0
        if limit:
            self.limit = limit

        self.sort_column = None

        self.filters = None
        self.filtered_rows = blist()

        kwargs = dict(
            columns = self.column_names,
            use_blist=True,
            sort=False,
            index_name = self.index or None
            # sorted=True,
        )
        # if self.index:
        #     kwargs["index_name"] = self.index

        # self.df = DataTableDataFrame(**kwargs)
        self.df = DataTableDataFrame(
            columns = self.column_names,
            use_blist=True,
            sort=False,
            index_name = self.index or None
        )

        self.pile = urwid.Pile([])
        self.listbox = ScrollingListBox(
            self, infinite=self.limit,
            with_scrollbar = self.with_scrollbar,
            row_count_fn = self.row_count
        )

        urwid.connect_signal(
            self.listbox, "select",
            lambda source, selection: urwid.signals.emit_signal(
                self, "select", self, self.get_dataframe_row(selection.index))
        )
        urwid.connect_signal(
            self.listbox, "drag_start",
            lambda source, drag_from: urwid.signals.emit_signal(
                self, "drag_start", self, drag_from)
        )
        urwid.connect_signal(
            self.listbox, "drag_continue",
            lambda source, drag_from, drag_to: urwid.signals.emit_signal(
                self, "drag_continue", self, drag_from, drag_to)
        )
        urwid.connect_signal(
            self.listbox, "drag_stop",
            lambda source, drag_from ,drag_to: urwid.signals.emit_signal(
                self, "drag_stop", self, drag_from, drag_to)
        )

        if self.limit:
            urwid.connect_signal(self.listbox, "load_more", self.load_more)
            # self.offset = 0

        if self.with_header:
            self.header = DataTableHeaderRow(
                self,
                border = self.border,
                padding = self.padding,
            )

            self.pile.contents.insert(
                0,
                (
                    urwid.Columns([
                        ("weight", 1, self.header),
                        (1, urwid.Text(("table_row_header", " ")))
                    ]),
                    self.pile.options('pack')
                )
             )

            if self.ui_sort:
                urwid.connect_signal(
                    self.header, "column_click",
                    lambda index: self.sort_by_column(index, toggle=True)
                )

            if self.ui_resize:
                urwid.connect_signal(self.header, "drag", self.on_header_drag)

        self.pile.contents.append(
            (self.listbox, self.pile.options('weight', 1))
         )
        self.pile.focus_position = len(self.pile.contents)-1

        if self.with_footer:
            self.footer = DataTableFooterRow(
                self,
                border = self.border,
                padding = self.padding
            )
            self.pile.contents.append(
                (self.footer, self.pile.options('pack'))
             )


        if not self.no_load_on_init:
            self.reset()

            if self.sort_by:
                self.sort_by_column(self.sort_by)


        self.attr = urwid.AttrMap(
            self.pile,
            attr_map = self.attr_map,
            # focus_map = self.focus_map
        )
        super(DataTable, self).__init__(self.attr)


    def query(self, sort=None, offset=None):
        raise Exception("query method must be overriden")

    def query_result_count(self):
        raise Exception("query_result_count method must be defined")

    @classmethod
    def get_palette_entries(
            cls,
            user_entries={},
            min_contrast_entries = None,
            min_contrast = 2.0,
            default_background="black"
    ):


        foreground_map = {
            "table_row_body": [ "light gray", "light gray" ],
            "table_row_header": [ "light gray", "white" ],
            "table_row_footer": [ "light gray", "white" ],
        }

        background_map = {
            None: [ "black", "black" ],
            "focused": [ "dark gray", "g15" ],
            "column_focused": [ "black", "#660" ],
            "highlight": ["light gray", "g15"],
            "highlight focused": ["light gray", "g23"],
            "highlight column_focused": ["light gray", "#660"],
        }

        entries = dict()

        row_attr = "table_row_body"
        for suffix in [None, "focused", "column_focused",
                       "highlight", "highlight focused",
                       "highlight column_focused",
        ]:
            if suffix:
                attr = ' '.join([row_attr, suffix])
            else:
                attr = row_attr
            entries[attr] = urwid_utils.palette.PaletteEntry(
                mono = "white",
                foreground = foreground_map[row_attr][0],
                background = background_map[suffix][0],
                foreground_high = foreground_map[row_attr][1],
                background_high = background_map[suffix][1],
            )

        header_foreground_map = {
            None: ["white,bold", "white,bold"],
            "focused": ["dark gray", "white,bold"],
            "column_focused": ["black", "black"],
            "highlight": ["yellow,bold", "yellow,bold"],
            "highlight focused": ["yellow", "yellow"],
            "highlight column_focused": ["yellow", "yellow"],
        }

        header_background_map = {
            None: ["light gray", "g23"],
            "focused": ["light gray", "g50"],
            "column_focused": ["white", "g70"],#"g23"],
            "highlight": ["light gray", "g38"],
            "highlight focused": ["light gray", "g50"],
            "highlight column_focused": ["white", "g70"],
        }

        for prefix in ["table_row_header", "table_row_footer"]:
            for suffix in [
                    None, "focused", "column_focused",
                    "highlight", "highlight focused",
                    "highlight column_focused"
            ]:
                if suffix:
                    attr = ' '.join([prefix, suffix])
                else:
                    attr = prefix
                entries[attr] = urwid_utils.palette.PaletteEntry(
                    mono = "white",
                    foreground = header_foreground_map[suffix][0],
                    background = header_background_map[suffix][0],
                    foreground_high = header_foreground_map[suffix][1],
                    background_high = header_background_map[suffix][1],
                )


        for name, entry in list(user_entries.items()):
            DataTable.focus_map[name] = "%s focused" %(name)
            DataTable.highlight_map[name] = "%s highlight" %(name)
            DataTable.column_focus_map["%s focused" %(name)] = "%s column_focused" %(name)
            DataTable.highlight_focus_map["%s highlight" %(name)] = "%s highlight focused" %(name)
            for suffix in [None, "focused", "column_focused",
                           "highlight", "highlight focused",
                           "highlight column_focused",
            ]:

                # Check entry backgroun colors against default bg.  If they're
                # the same, replace the entry's background color with focus or
                # highglight color.  If not, preserve the entry background.

                default_bg_rgb = urwid.AttrSpec(default_background, default_background, 16)
                bg_rgb = urwid.AttrSpec(entry.background, entry.background, 16)
                background = background_map[suffix][0]
                if default_bg_rgb.get_rgb_values() != bg_rgb.get_rgb_values():
                    background = entry.background

                background_high = background_map[suffix][1]
                if entry.background_high:
                    bg_high_rgb = urwid.AttrSpec(
                        entry.background_high,
                        entry.background_high,
                        (1<<24
                         if urwid_utils.palette.URWID_HAS_TRUE_COLOR
                         else 256
                        )
                    )
                    if default_bg_rgb.get_rgb_values() != bg_high_rgb.get_rgb_values():
                        background_high = entry.background_high

                foreground = entry.foreground
                background = background
                foreground_high = entry.foreground_high if entry.foreground_high else entry.foreground
                if min_contrast_entries and name in min_contrast_entries:
                    # All of this code is available in the colourettu package
                    # (https://github.com/MinchinWeb/colourettu) but newer
                    # versions don't run Python 3, and older versions don't work
                    # right.
                    def normalized_rgb(r, g, b):

                        r1 = r / 255
                        g1 = g / 255
                        b1 = b / 255

                        if r1 <= 0.03928:
                            r2 = r1 / 12.92
                        else:
                            r2 = math.pow(((r1 + 0.055) / 1.055), 2.4)
                        if g1 <= 0.03928:
                            g2 = g1 / 12.92
                        else:
                            g2 = math.pow(((g1 + 0.055) / 1.055), 2.4)
                        if b1 <= 0.03928:
                            b2 = b1 / 12.92
                        else:
                            b2 = math.pow(((b1 + 0.055) / 1.055), 2.4)

                        return (r2, g2, b2)

                    def luminance(r, g, b):

                        return math.sqrt(
                            0.299*math.pow(r, 2) +
                            0.587*math.pow(g, 2) +
                            0.114*math.pow(b, 2)
                        )

                    def contrast(c1, c2):

                        n1 = normalized_rgb(*c1)
                        n2 = normalized_rgb(*c2)
                        lum1 = luminance(*n1)
                        lum2 = luminance(*n2)
                        minlum = min(lum1, lum2)
                        maxlum = max(lum1, lum2)
                        return (maxlum + 0.05) / (minlum + 0.05)

                    table_bg = background_map[suffix][1]
                    attrspec_bg = urwid.AttrSpec(table_bg, table_bg, 256)
                    color_bg = attrspec_bg.get_rgb_values()[3:6]
                    attrspec_fg = urwid.AttrSpec(
                        foreground_high,
                        foreground_high,
                        256
                    )
                    color_fg = attrspec_fg.get_rgb_values()[0:3]
                    cfg = contrast(color_bg, color_fg)
                    cblack = contrast((0,0,0), color_fg)
                    # cwhite = contrast((255, 255, 255), color_fg)
                    # logger.info("%s, %s, %s" %(cfg, cblack, cwhite))
                    # raise Exception("%s, %s, %s, %s, %s, %s" %(table_bg, color_fg, color_bg, cfg, cblack, cwhite))
                    if cfg < min_contrast and cfg < cblack:
                        # logger.info("adjusting contrast of %s" %(name))
                        foreground_high = "black"
                        # if cblack > cwhite:
                        # else:
                        #     foreground_high = "white"

                if suffix:
                    attr = ' '.join([name, suffix])
                else:
                    attr = name

                # print foreground, foreground_high, background, background_high
                entries[attr] = urwid_utils.palette.PaletteEntry(
                    mono = "white",
                    foreground = foreground,
                    background = background,
                    foreground_high = foreground_high,
                    background_high = background_high,
                )


        # raise Exception(entries)
        return entries


    @property
    def focus(self): return self._focus

    def next_position(self, position):
        index = position + 1
        if index > len(self.filtered_rows): raise IndexError
        return index

    def prev_position(self, position):
        index = position-1
        if index < 0: raise IndexError
        return index

    def set_focus(self, position):
        # logger.debug("walker set_focus: %d" %(position))
        self._emit("blur", self._focus)
        self._focus = position
        self._emit("focus", position)
        self._modified()

    def _modified(self):
        # self.focus_position = 0
        urwid.listbox.ListWalker._modified(self)

    def positions(self, reverse=False):
        if reverse:
            return range(len(self) - 1, -1, -1)
        return range(len(self))

    def __getitem__(self, position):
        # logger.debug("walker get: %d" %(position))
        if isinstance(position, slice):
            return [self[i] for i in range(*position.indices(len(self)))]
        if position < 0 or position >= len(self.filtered_rows): raise IndexError
        try:
            r = self.get_row_by_position(position)
            return r
        except IndexError:
            logger.error(traceback.format_exc())
            raise
        # logger.debug("row: %s, position: %s, len: %d" %(r, position, len(self)))

    def __delitem__(self, position):
        if isinstance(position, slice):
            indexes = [self.position_to_index(p)
                       for p in range(*position.indices(len(self)))]
            self.delete_rows(indexes)
            # for i in range(*position.indices(len(self))):
            #     print(f"{position}, {i}")
            #     del self[i]
        else:
            try:
                # raise Exception(position)
                i = self.position_to_index(self.filtered_rows[position])
                self.delete_rows(i)
            except IndexError:
                logger.error(traceback.format_exc())
                raise

    def __len__(self):
        return len(self.filtered_rows)

    def __getattr__(self, attr):
        if attr in [
                "head",
                "tail",
                "index_name",
                "log_dump",
        ]:
            return getattr(self.df, attr)
        elif attr in ["body"]:
            return getattr(self.listbox, attr)
        else:
            return object.__getattribute__(self, attr)
        # elif attr == "body":
        #     return self.walker
        # raise AttributeError(attr)

    def decorate(self, row, column, value):
        if column.decoration_fn:
            value = column.decoration_fn(value)
        if not isinstance(value, urwid.Widget):
            if not isinstance(value, tuple):
                value = str(value)
            try:
                value = DataTableText(value, align=column.align, wrap=column.wrap)
            except:
                raise Exception(value, type(value))
        return value

    @property
    def column_names(self):
        return [c.name for c in self.columns]

    @property
    def focus_position(self):
        return self._focus
        # return self.listbox.focus_position

    @focus_position.setter
    def focus_position(self, value):
        self.set_focus(value)
        # self.listbox.focus_position = value
        self.listbox._invalidate()

    def position_to_index(self, position):
        # if not self.query_sort and self.sort_by[1]:
        #     position = -(position + 1)
        return self.df.index[position]

    def index_to_position(self, index):
        # raise Exception(index, self.df.index)
        return self.df.index.index(index)

    def get_dataframe_row(self, index):
        # logger.debug("__getitem__: %s" %(index))
        # try:
        #     v = self.df[index:index]
        # except IndexError:
        #     raise Exception
        #     # logger.debug(traceback.format_exc())

        try:
            d = self.df.get_columns(index, as_dict=True)
        except ValueError:
            raise Exception(index, self.df)
        cls = d.get("_cls")
        if cls:
            if hasattr(cls, "__dataclass_fields__"):
                # klass = type(f"DataTableRow_{cls.__name__}", [cls],
                klass = make_dataclass(
                    f"DataTableRow_{cls.__name__}",
                    [
                        ("_cls", typing.Optional[typing.Any], field(default=None)),
                    ],
                    bases=(cls,)
                )
                k = klass(
                    **{k: d[k]
                       for k in set(
                               cls.__dataclass_fields__.keys())
                    })

                return k
            else:
                return cls(**d)
        else:
            return AttrDict(**d)
        # if isinstance(d, MutableMapping):
        #     cls = d.get("_cls")
        # else:
        #     cls = getattr(d, "_cls")

        # if cls:
        #     return cls(**d)
        # else:
        #     return AttrDict(**d)

    def get_row(self, index):
        try:
            row = self.df.get(index, "_rendered_row")
        except:
            raise

        if self.df.get(index, "_dirty") or row is None:
            self.refresh_calculated_fields([index])
            # vals = self[index]
            vals = self.get_dataframe_row(index)
            row = self.render_item(index)
            if self.row_attr_fn:
                attr = self.row_attr_fn(vals)
                if attr:
                    row.set_attr(attr)
            focus = self.df.get(index, "_focus_position")
            if focus is not None:
                row.set_focus_column(focus)
            self.df.set(index, "_rendered_row", row)
            self.df.set(index, "_dirty", False)
        return row

    def get_row_by_position(self, position):
        index = self.position_to_index(self.filtered_rows[position])
        return self.get_row(index)

    def get_value(self, row, column):
        return self.df[self.position_to_index(row), column]

    def set_value(self, row, column, value):
        self.df.set(self.position_to_index(row), column, value)

    @property
    def selection(self):
        if len(self.body) and self.focus_position is not None:
            # FIXME: make helpers to map positions to indexes
            return self[self.focus_position]


    def render_item(self, index):
        row = DataTableBodyRow(self, index,
                               border = self.border,
                               padding = self.padding,
                               # index=data[self.index],
                               cell_selection = self.cell_selection)
        return row

    def refresh_calculated_fields(self, indexes=None):
        if not indexes:
            indexes = self.df.index[:]
        if not hasattr(indexes, "__len__"):
            indexes = [indexes]
        for col in self.columns:
            if not col.value_fn: continue
            for index in indexes:
                if self.df[index, "_dirty"]:
                    self.df.set(index, col.name, col.value_fn(self, self.get_dataframe_row(index)))

    def visible_column_index(self, column_name):
        try:
            return next(i for i, c in enumerate(self.visible_columns)
                     if c.name == column_name)

        except StopIteration:
            raise IndexError

    def sort_by_column(self, col=None, reverse=None, toggle=False):

        column_name = None
        column_number = None

        if isinstance(col, tuple):
            col, reverse = col

        elif col is None:
            col = self.sort_column

        if isinstance(col, int):
            try:
                column_name = self.visible_columns[col].name
            except IndexError:
                raise Exception("bad column number: %d" %(col))
            column_number = col
        elif isinstance(col, str):
            column_name = col
            try:
                column_number = self.visible_column_index(column_name)
            except:
                column_number = None

        self.sort_column = column_number

        if not column_name:
            return
        try:
            column = next((c for c in self.columns if c.name == column_name))
        except:
            return # FIXME

        if reverse is None and column.sort_reverse is not None:
            reverse = column.sort_reverse

        if toggle and column_name == self.sort_by[0]:
            reverse = not self.sort_by[1]
        sort_by = (column_name, reverse)
        # if not self.query_sort:

        self.sort_by = sort_by
        logger.info("sort_by: %s (%s), %s" %(column_name, self.sort_column, reverse))
        if self.query_sort:
            self.reset()

        row_index = None
        if self.sort_refocus:
            row_index = self[self._focus].data.get(self.index, None)
            logger.info("row_index: %s" %(row_index))
        self.sort(column_name, key=column.sort_key)

        if self.with_header:
            self.header.update_sort(self.sort_by)

        self.set_focus_column(self.sort_column)
        if row_index:
            self.focus_position = self.index_to_position(row_index)

    def sort(self, column, key=None):
        import functools
        logger.debug(column)
        if not key:
            key = lambda x: (x is None, x)
        self.df.sort_columns(
            column,
            key = key,
            reverse = self.sort_by[1])
        self._modified()


    def set_focus_column(self, index):
        if self.with_header:
            self.header.set_focus_column(self.sort_column)

        if self.with_footer:
            self.footer.set_focus_column(self.sort_column)

        # logger.debug("set_focus_column: %d" %(index))
        self.df["_focus_position"] = index
        self.df["_dirty"] = True

    def cycle_sort_column(self, step):

        if not self.ui_sort:
            return
        if self.sort_column is None:
            index = 0
        else:
            index = (self.sort_column + step)
            if index < 0: index = len(self.visible_columns)-1
            if index > len(self.visible_columns)-1: index = 0
        logger.debug("index: %d" %(index))
        self.sort_by_column(index)

    def sort_index(self):
        self.df.sort_index()
        self._modified()

    def add_columns(self, columns, data=None):

        if not isinstance(columns, list):
            columns = [columns]
            if data:
                data = [data]

        self.columns += columns
        for i, column in enumerate(columns):
            self.df[column.name] = data=data[i] if data else None

        self.invalidate()

    def remove_columns(self, columns):

        if not isinstance(columns, list):
            columns = [columns]

        columns = [ self.columns[column].name
                    if isinstance(column, int)
                    else column for column in columns ]

        self.columns = [ c for c in self.columns if c.name not in columns ]
        self.df.delete_columns(columns)
        self.invalidate()

    def set_columns(self, columns):
        self.remove_columns([c.name for c in self.columns])
        self.add_columns(columns)
        self.reset()

    def toggle_columns(self, columns, show=None):

        if not isinstance(columns, list):
            columns = [columns]

        for column in columns:
            if isinstance(column, int):
                try:
                    column = self.columns[column]
                except IndexError:
                    raise Exception("bad column number: %d" %(column))
            else:
                try:
                    column = next(( c for c in self.columns if c.name == column))
                except IndexError:
                    raise Exception("column %s not found" %(column))

            if show is None:
                column.hide = not column.hide
            else:
                column.hide = show
        self.invalidate()

    def show_columns(self, columns):
        self.toggle_columns(columns, True)

    def hide_columns(self, columns):
        self.show_column(columns, False)

    def resize_column(self, name, size):

        index, col = next( (i, c) for i, c in enumerate(self.columns) if c.name == name)
        if isinstance(size, tuple):
            col.sizing, col.width = size
        elif isinstance(size, int):
            col.sizing = "given"
            col.width = size
        else:
            raise NotImplementedError
        if self.with_header:
            self.header.update()
        for r in self:
            r.update()
        if self.with_footer:
            self.footer.update()
        #     r.resize_column(index, size)

    def on_header_drag(self, source, source_column, start, end):

        def resize_columns(cols, mins, index, delta, direction):
            logger.info(f"cols: {cols}, mins: {mins}, index: {index}, delta: {delta}, direction: {direction}")
            new_cols = [c for c in cols]

            if direction == 1 or index == 0:
                indexes = range(index, len(cols))
            else:
                indexes = range(index, -1, -1)
            if len(indexes) < 2:
                raise Exception

            deltas = [a-b for a, b in zip(cols, mins)]
            logger.info(f"deltas: {deltas}")
            d = delta

            for n, i in enumerate(indexes):
                logger.info(f"i: {i}, d: {d}")

                if delta < 0:
                    # can only shrink down to minimum for this column
                    logger.info(f"{d}, {-deltas[i]}")
                    d = max(delta, -deltas[i])
                    logger.info(f"shrinking: {d}")
                elif delta > 0:
                    # can only grow to maximum of remaining deltas?
                    d = min(delta, sum([ deltas[x] for x in indexes[1:]]))
                    logger.info(f"growing: {d}")
                else:
                    continue

                new_cols[i] += d

                if i == index:
                    delta = -d
                    d = delta
                    indexes = list(reversed(indexes))
                    logger.info(f"reversing: {d}")
                else:
                    delta -= d
                    if delta == 0:
                        break

            return new_cols

        try:
            index = next(
                i for i, c in enumerate(self.header.columns.contents)
                if c[0] == source
            )
        except StopIteration:
            return

        if isinstance(source, DataTableHeaderCell):
            cell = source
        else:
            # index+=1
            cell = self.header.columns.contents[index-1][0]

        colname = cell.column.name
        logger.info(colname)
        column = next( c for c in self.columns if c.name == colname)
        index = index//2

        new_width = old_width = column.width

        delta = end-start
        if isinstance(source, DataTableColumnDivider):
            # logger.info("divider")
            drag_direction= 1#abs(delta)//delta
        elif index != 0 and source_column <= int(round(column.width / 3)):
            drag_direction=-1
            delta = -delta
        elif index != len(self.visible_columns)-1 and source_column >= int(round( (2*cell.width) / 3)):
            drag_direction=1
        else:
           return

        widths = [ c.width for c in self.header.cells ]
        mins = [ c.contents_width for c in self.header.cells ]
        new_widths = resize_columns(widths, mins, index, delta, drag_direction)

        for i, c in enumerate(self.visible_columns):
            if self.header.cells[i].width != new_widths[i]:
                self.resize_column(c.name, new_widths[i])

        logger.info(f"{widths}, {new_widths}")
        if sum(widths) != sum(new_widths):
            logger.warning(f"{sum(widths)} != {sum(new_widths)}")

    def toggle_details(self):
        self.selection.toggle_details()

    def enable_cell_selection(self):
        logger.debug("enable_cell_selection")
        for r in self:
            r.enable_cell_selection()
        self.reset()
        self.cell_selection = True

    def disable_cell_selection(self):
        logger.debug("disable_cell_selection")
        for r in self:
            r.disable_cell_selection()
        self.reset()
        self.cell_selection = False

    def toggle_cell_selection(self):
        if self.cell_selection:
            self.disable_cell_selection()
        else:
            self.enable_cell_selection()

    @property
    def visible_columns(self):
        return [ c for c in self.columns if not c.hide ]

    def add_row(self, data, sort=True):

        self.append_rows([data])
        if sort:
            self.sort_by_column()
        self.apply_filters()
        # else:
        #     self.invalidate()

    def delete_rows(self, indexes):

        self.df.delete_rows(indexes)
        self.apply_filters()
        if self.focus_position >= len(self)-1:
            self.focus_position = len(self)-1


    def invalidate(self):
        self.df["_dirty"] = True
        if self.with_header:
            self.header.update()
        if self.with_footer:
            self.footer.update()
        self._modified()

    def invalidate_rows(self, indexes):
        if not isinstance(indexes, list):
            indexes = [indexes]
        for index in indexes:
            self.refresh_calculated_fields(index)

        self.df[indexes, "_dirty"] = True
        self._modified()
        # FIXME: update header / footer if dynamic

    def swap_rows_by_field(self, p0, p1, field=None):

        if not field:
            field=self.index

        i0 = self.position_to_index(p0)
        i1 = self.position_to_index(p1)

        r0 = { k: v[0] for k, v in list(self.df[i0, None].to_dict().items()) }
        r1 = { k: v[0] for k, v in list(self.df[i1, None].to_dict().items()) }

        for k, v in list(r0.items()):
            if k != field:
                self.df.set(i1, k, v)

        for k, v in list(r1.items()):
            if k != field:
                self.df.set(i0, k, v)
        self.df.set(i0, "_dirty", True)

        self.invalidate_rows([i0, i1])

    def swap_rows(self, p0, p1, field=None):
        self.swap_rows_by_field(p0, p1, field=field)

    def row_count(self):

        if not self.limit:
            return None

        if self.limit:
            return self.query_result_count()
        else:
            return len(self)

    def apply_filters(self, filters=None):

        if not filters:
            filters = self.filters
        elif not isinstance(filters, list):
            filters = [filters]

        self.filtered_rows = blist(
            i
            for i, row in enumerate(self.df.iterrows())
            if not filters or all(
                    f(row)
                    for f in filters
            )
        )
        # if self.focus_position > len(self):
        #     self.focus_position = len(self)-1

        # logger.info("filtered: %s" %(self.filtered_rows))


        self.filters = filters
        self.invalidate()

    def clear_filters(self):
        self.filtered_rows = blist(range(len(self.df)))
        self.filters = None
        self.invalidate()


    def load_all(self):
        if len(self) >= self.query_result_count():
            return
        logger.info("load_all: %s" %(self.page))
        self.requery(self.page*self.limit, load_all=True)
        self.page = (self.query_result_count() // self.limit)
        self.listbox._invalidate()


    def load_more(self, position):

        # logger.info("load_more")
        if position is not None and position > len(self):
            return False
        self.page = len(self) // self.limit
        offset = (self.page)*self.limit
        # logger.info(f"offset: {offset}, row count: {self.row_count()}")
        if (self.row_count() is not None
            and len(self) >= self.row_count()):

            return False

        try:
            self.requery(offset=offset)
        except Exception as e:
            raise Exception(f"{position}, {len(self)}, {self.row_count()}, {offset}, {self.limit}, {e}")

        return True

    def requery(self, offset=None, limit=None, load_all=False, **kwargs):
        # logger.info(f"requery: {offset}, {limit}")
        if (offset is not None) and self.limit:
            self.page = offset // self.limit
            offset = self.page*self.limit
            limit = self.limit
        elif self.limit:
            self.page = (limit // self.limit)
            limit = (self.page) * self.limit
            offset = 0

        if offset:
            df = self.df
        else:
            df = DataTableDataFrame(
                columns = self.column_names,
                use_blist=True,
                sort=False,
                index_name = self.index or None
            )

        # logger.info("requery")
        kwargs = {"load_all": load_all}
        if self.query_sort:
            kwargs["sort"] = self.sort_by
        else:
            kwargs["sort"] = (None, False)
        limit = limit or self.limit
        if limit:
            kwargs["offset"] = offset
            kwargs["limit"] = limit

        if self.data is not None:
            rows = self.data
        else:
            rows = list(self.query(**kwargs))

        for row in rows:
            row["_cls"] = type(row)
            # if isinstance(row, MutableMapping):
            # else:
            #     setattr(row, "_cls", type(row))
        df.append_rows(rows)
        df["_focus_position"] = self.sort_column
        if not offset:
            self.df = df

        self.invalidate()
        self._modified()
        # try:
        #     self.append_rows(rows)
        # except:
        #     logger.error(f"{kwargs}, {rows}")
        #     raise
        self.refresh_calculated_fields()
        self.apply_filters()
        # if pos < len(self):
        #     self.focus_position = pos


    def refresh(self, reset=False):
        offset = None
        idx = None
        pos = 0
        # limit = len(self)-1
        if reset:
            self.page = 0
            offset = 0
            limit = self.limit
        else:
            try:
                idx = getattr(self.selection.data, self.index)
            except (AttributeError, IndexError):
                pass
            pos = self.focus_position
            limit = len(self)
        # del self[:]
        self.requery(offset=offset, limit=limit)
        if idx:
            try:
                pos = self.index_to_position(idx)
            except:
                pass
        self.focus_position = pos
        # self.focus_position = 0


    def reset(self, reset_sort=False):
        self.refresh(reset=True)
        # self.clear_filters()
        # self.apply_filters()
        if reset_sort:
            self.sort_by_column(self.initial_sort)

    def load(self, path):

        with open(path, "r") as f:
            json = "\n".join(f.readlines())
            self.df = DataTableDataFrame.from_json(json)
        self.reset()

    def save(self, path):
        # print(path)
        with open(path, "w") as f:
            f.write(self.df.to_json())

__all__ = ["DataTable", "DataTableColumn"]
