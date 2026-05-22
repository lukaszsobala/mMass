import wx
from . import config

class dlgSettings(wx.Dialog):
    """Settings dialog."""

    def __init__(self, parent):
        wx.Dialog.__init__(
            self, parent, -1, "Settings",
            style=wx.DEFAULT_DIALOG_STYLE | wx.RESIZE_BORDER,
        )

        self.parent = parent
        self.Bind(wx.EVT_CLOSE, self.onClose)

        self.quality_slider = wx.Slider(self, -1, 
            value=self._get_slider_value(config.spectrum.get("filterSize", 1.0)), 
            minValue=10, maxValue=50,
            style=wx.SL_HORIZONTAL | wx.SL_AUTOTICKS)

        self.quality_label = wx.StaticText(self, -1, f"Quality: {self.quality_slider.GetValue()/10.0:.1f}")

        # Apply immediately on slider move!
        self.quality_slider.Bind(wx.EVT_SLIDER, self.onScroll)

        # layout
        sizer = wx.BoxSizer(wx.VERTICAL)
        
        box = wx.StaticBox(self, -1, "Spectrum quality (1.0 = fastest, 5.0 = best)")
        box_sizer = wx.StaticBoxSizer(box, wx.VERTICAL)
        box_sizer.Add(self.quality_label, 0, wx.ALL | wx.ALIGN_CENTER_HORIZONTAL, 5)
        box_sizer.Add(self.quality_slider, 0, wx.ALL | wx.EXPAND, 10)
        
        sizer.Add(box_sizer, 0, wx.ALL | wx.EXPAND, 10)
        self.SetSizer(sizer)
        sizer.Fit(self)
        
    def _get_slider_value(self, filterSize):
        return max(10, min(50, int(round((6.0 - float(filterSize)) * 10))))

    def _get_filter_size(self, slider_val):
        return round(6.0 - (slider_val / 10.0), 1)

    def onScroll(self, evt):
        slider_val = self.quality_slider.GetValue()
        self.quality_label.SetLabel(f"Quality: {slider_val/10.0:.1f}")
        config.spectrum["filterSize"] = self._get_filter_size(slider_val)
        if hasattr(self.parent, 'spectrumPanel') and self.parent.spectrumPanel:
            if hasattr(self.parent.spectrumPanel, 'updateCanvasProperties'):
                self.parent.spectrumPanel.updateCanvasProperties()
            elif hasattr(self.parent.spectrumPanel, 'spectrumCanvas'):
                self.parent.spectrumPanel.spectrumCanvas.setProperties(filterSize=config.spectrum["filterSize"])
                self.parent.spectrumPanel.spectrumCanvas.refresh()
        evt.Skip()
        
    def onClose(self, evt):
        self.Destroy()
        evt.Skip()

