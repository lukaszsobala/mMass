import re

with open('mspy/obj_scan.py', 'r') as f:
    content = f.read()

def replace_empty_pattern(code):
    pattern = r'(self\.profile = mod_signal\.\w+\(self\.profile, other\.profile\)\n\n\s+)# empty peaklist\n\s+self\.peaklist\.empty\(\)'
    replacement = r'''\1if not preservePeaks:
                self.peaklist.empty()
            elif len(self.peaklist) > 0 and len(self.profile) > 0:
                import numpy
                peak_mzs = numpy.array([p.mz for p in self.peaklist.peaks])
                prof_vals = numpy.interp(peak_mzs, self.profile[:, 0], self.profile[:, 1])
                for i, peak in enumerate(self.peaklist.peaks):
                    peak.ai = prof_vals[i]
                    peak.reset()
                self.peaklist._setbasepeak()
                self.peaklist._setRelativeIntensities()'''
    return re.sub(pattern, replacement, code)

new_content = replace_empty_pattern(content)

with open('mspy/obj_scan.py', 'w') as f:
    f.write(new_content)
