import panel as pn
import param
import bokeh.palettes
import numpy as np
import numpy.typing as npt
import pandas as pd

from matplotlib.colors import to_rgb
from sklearn.neighbors import NearestNeighbors

from .utils import _palette_index

from typing import *

BRUSH_ON_MESSAGE = "Brush is **on**. Left-click to stop brushing."
BRUSH_OFF_MESSAGE = (
    "Brush currently **off**. Left-click to enable the brush and start brushing"
)
ERASER_ON_MESSAGE = "Eraser is **on**. Left-click to stop erasing."
ERASER_OFF_MESSAGE = (
    "Eraser currently **off**. Left-click to enable the eraser and start erasing"
)

MAGIC_ZOOM_CONSTANT = 8.720671786825559


class DeckglPlotPane(pn.viewable.Viewer, pn.reactive.Reactive):
    labels = param.Series(doc="Labels")
    color_palette = param.List([], item_type=str, doc="Color palette")
    color_factors = param.List([], item_type=str, doc="Color palette")
    selected = param.List([], doc="Indices of selected samples")

    def __init__(
        self,
        data: npt.ArrayLike,
        labels: Iterable[str],
        annotation: Optional[Iterable[str]] = None,
        size: Optional[Iterable[float]] = None,
        *,
        label_color_mapping: Optional[Dict[str, str]] = None,
        palette: Sequence[str] = bokeh.palettes.Turbo256,
        width: int = 600,
        height: int = 600,
        selection_brush_radius=0.1,
        max_point_size: Optional[float] = None,
        min_point_size: Optional[float] = None,
        fill_alpha: float = 0.75,
        line_color: str = "white",
        hover_fill_color: str = "red",
        background_fill_color: str = "#ffffff",
        selection_fill_alpha: float = 1.0,
        nonselection_fill_alpha: float = 0.1,
        nonselection_fill_color: str = "gray",
        title: Optional[str] = None,
        show_selection_controls=True,
        name: str = "Plot",
    ):
        super().__init__(name=name)
        self.dataframe = pd.DataFrame(
            {
                "position": data.tolist(),
                "label": labels,
                "annotation": annotation,
                "size": size if size is not None else np.full(data.shape[0], 0.1),
            }
        )

        self._fill_alpha_int = int(round(255 * fill_alpha))
        self._selection_fill_alpha_int = int(round(255 * selection_fill_alpha))
        self._nonselection_fill_color = [
            int(c * 255) for c in to_rgb(nonselection_fill_color)
        ] + [int(round(255 * nonselection_fill_alpha))]

        if label_color_mapping is not None:
            base_color_factors = []
            base_color_palette = []
            for label, color in label_color_mapping.items():
                base_color_factors.append(label)
                base_color_palette.append(color)
            base_color_palette = base_color_palette + [
                palette[x] for x in _palette_index(len(palette))
            ]
        else:
            base_color_palette = [palette[x] for x in _palette_index(256)]
            base_color_factors = list(set(labels))

        self.color_mapping = {
            label: ([int(c * 255) for c in to_rgb(color)] + [self._fill_alpha_int])
            for label, color in zip(base_color_factors, base_color_palette)
        }

        self.dataframe["color"] = self.dataframe.label.map(self.color_mapping)
        self.brush_radius = selection_brush_radius

        self._color_loc = self.dataframe.columns.get_loc("color")
        self._selected_set = set([])
        self._selected_externally_changed = True
        self._nn_index = NearestNeighbors().fit(data)
        self._brushing_on = False
        self._color_map_in_selection_mode = False

        self.points = {
            "@@type": "ScatterplotLayer",
            "data": [],
            "getColor": "@@=color",
            "getPosition": "@@=position",
            "getRadius": "@@=size",
            "lineWidthUnits": "pixels",
            "stroked": True,
            "getLineColor": [int(c * 255) for c in to_rgb(line_color)],
            "getLineWidth": 0.6,
            "lineWidthMinPixels": 0.4,
            "lineWidthMaxPixels": 0.8,
            "pickable": True,
            "autoHighlight": True,
            "highlightColor": [int(c * 255) for c in to_rgb(hover_fill_color)],
            "radiusMinPixels": min_point_size if min_point_size is not None else 0.5,
            "radiusMaxPixels": max_point_size if max_point_size is not None else 32,
        }
        view_center = np.mean(data, axis=0)
        view_size = max(
            np.max(data.T[0]) - np.min(data.T[0]), np.max(data.T[1]) - np.min(data.T[1])
        )
        zoom = MAGIC_ZOOM_CONSTANT - np.log2(view_size)
        self._base_radius = view_size * self.brush_radius

        self.deck = {
            "initialViewState": {
                "zoom": zoom,
                "target": [view_center[0], view_center[1]],
            },
            "layers": [self.points],
            "mapStyle": "",
            "views": [{"@@type": "OrthographicView", "controller": True}],
            "parameters": {
                "clearColor": [x for x in to_rgb(background_fill_color)] + [1.0]
            },
        }
        self.select_method = pn.widgets.RadioButtonGroup(
            name="Selection Method",
            options=["None", "Click", "Brush", "Brush-Erase", "Reset"],
            button_type="default",
            height=32,
        )
        self.select_controls = pn.Row(
            pn.widgets.StaticText(
                value="Selection Method:",
                height=32,
                style={
                    "font-weight": "bold",
                    "line-height": "32px",
                    "height": "64px",
                    "text-align": "right",
                },
                margin=[5, 0],
            ),
            self.select_method,
        )
        self.select_method.param.watch(
            self._change_selection_type, "value", onlychanged=True
        )
        self.select_message = pn.pane.Alert(
            "", alert_type="primary", sizing_mode="stretch_width", visible=False,
        )
        self.pane_deck = pn.pane.DeckGL(
            self.deck,
            sizing_mode="stretch_width",
            width=width,
            height=height,
            tooltips={"html": "{annotation}"},
        )
        self.title = pn.widgets.StaticText(
            value="Selection Method:",
            height=32,
            width=width,
            style={
                "font-weight": "bold",
                "font-size": "32px",
                "line-height": "32px",
                "height": "64px",
                "text-align": "left",
            },
            margin=[5, 0],
        )
        self.points["data"] = self.dataframe
        self.pane_deck.param.trigger("object")
        self.pane_deck.param.watch(
            self._click_event_handler, "click_state", onlychanged=True
        )
        self.pane_deck.param.watch(self._hover_event_handler, "hover_state")

        self.pane = pn.Column(
            self.select_controls, self.select_message, self.title, self.pane_deck
        )
        self.select_controls.visible = show_selection_controls
        self.title.visible = title is not None
        self.labels = pd.Series(labels)
        self.color_palette = base_color_palette
        self.color_factors = base_color_factors

    # Reactive requires this to make the model auto-display as requires
    def _get_model(self, *args, **kwds):
        return self.pane._get_model(*args, **kwds)

    def _hover_event_handler(self, event):
        if self.select_method.value == "Brush":
            if self._brushing_on:
                if len(self.pane_deck.view_state) > 0:
                    radius = (
                        self.pane_deck.view_state["se"][0]
                         - self.pane_deck.view_state["nw"][0]
                    ) * self.brush_radius
                else:
                    radius = self._base_radius

                neighbors = self._nn_index.radius_neighbors(
                    [event.new["coordinate"]],
                    radius=radius,
                    return_distance=False,
                )
                self._selected_set.update(neighbors[0])
                self._remap_colors(list(self._selected_set))
                self._selected_externally_changed = False
                self.selected = list(self._selected_set)
                self._selected_externally_changed = True
        elif self.select_method.value == "Brush-Erase":
            if self._brushing_on:
                if len(self.pane_deck.view_state) > 0:
                    radius = (
                        self.pane_deck.view_state["se"][0]
                         - self.pane_deck.view_state["nw"][0]
                    ) * self.brush_radius
                else:
                    radius = self._base_radius

                neighbors = self._nn_index.radius_neighbors(
                    [event.new["coordinate"]],
                    radius=radius,
                    return_distance=False,
                )
                self._selected_set.difference_update(neighbors[0])
                self._remap_colors(list(self._selected_set))
                self._selected_externally_changed = False
                self.selected = list(self._selected_set)
                self._selected_externally_changed = True

    def _click_event_handler(self, event):
        if self.select_method.value == "Click":
            if event.new["layer"] == "ScatterplotLayer":
                if event.new["index"] not in self._selected_set:
                    self._selected_set.add(event.new["index"])
                else:
                    self._selected_set.discard(event.new["index"])

                self._selected_externally_changed = False
                self.selected = list(self._selected_set)
                self._selected_externally_changed = True
        elif self.select_method.value == "Brush":
            if self._brushing_on:
                self._brushing_on = False
                self.select_message.visible = True
                self.select_message.alert_type = "primary"
                self.select_message.object = BRUSH_OFF_MESSAGE
            else:
                self._brushing_on = True
                self.select_message.visible = True
                self.select_message.alert_type = "success"
                self.select_message.object = BRUSH_ON_MESSAGE
        elif self.select_method.value == "Brush-Erase":
            if self._brushing_on:
                self._brushing_on = False
                self.select_message.visible = True
                self.select_message.alert_type = "primary"
                self.select_message.object = ERASER_OFF_MESSAGE
            else:
                self._brushing_on = True
                self.select_message.visible = True
                self.select_message.alert_type = "success"
                self.select_message.object = ERASER_ON_MESSAGE

    def _change_selection_type(self, event):
        if event.new == "Reset":
            self.select_message.visible = False
            self.selected = []
            self.pane_deck.throttle = {"view": 200, "hover": 200}
        elif event.new == "Brush":
            self._brushing_on = False
            self.select_message.visible = True
            self.select_message.alert_type = "primary"
            self.select_message.object = BRUSH_OFF_MESSAGE
            self.pane_deck.throttle = {"view": 200, "hover": 5}
        elif event.new == "Brush-Erase":
            self._brushing_on = False
            self.select_message.visible = True
            self.select_message.alert_type = "primary"
            self.select_message.object = ERASER_OFF_MESSAGE
            self.pane_deck.throttle = {"view": 200, "hover": 5}
        else:
            self.select_message.visible = False
            self.pane_deck.throttle = {"view": 200, "hover": 200}

    def _remap_colors(self, selected=None):
        if selected is None:
            return
        elif len(selected) > 0:
            self.dataframe["color"] = [self._nonselection_fill_color] * len(
                self.dataframe
            )
            if not self._color_map_in_selection_mode:
                self.color_mapping = {
                    key: color[:3] + [self._selection_fill_alpha_int]
                    for key, color in self.color_mapping.items()
                }
                self._color_map_in_selection_mode = True

            self.dataframe.iloc[
                selected, self._color_loc
            ] = self.dataframe.label.iloc[selected].map(self.color_mapping)
            self.points["data"] = self.dataframe
        else:
            if self._color_map_in_selection_mode:
                self.color_mapping = {
                    key: color[:3] + [self._fill_alpha_int]
                    for key, color in self.color_mapping.items()
                }
                self._color_map_in_selection_mode = False

            self.dataframe["color"] = self.dataframe.label.map(self.color_mapping)
            self.points["data"] = self.dataframe

        self.pane_deck.param.trigger("object")

    @param.depends("color_palette", watch=True)
    def _update_palette(self):
        self.color_mapping = {
            label: ([int(c * 255) for c in to_rgb(color)] + [self._fill_alpha_int])
            for label, color in zip(self.color_factors, self.color_palette)
        }
        self._remap_colors(self.selected)

    @param.depends("color_factors", watch=True)
    def _update_factors(self):
        self.color_mapping = {
            label: ([int(c * 255) for c in to_rgb(color)] + [self._fill_alpha_int])
            for label, color in zip(self.color_factors, self.color_palette)
        }
        self._remap_colors(self.selected)

    @param.depends("labels", watch=True)
    def _update_labels(self):
        self.dataframe["label"] = self.labels
        self._remap_colors(self.selected)

    @param.depends("selected", watch=True)
    def _update_selection(self):
        if self._selected_externally_changed:
            self._selected_set = set(self.selected)
            self._remap_colors(self.selected)
