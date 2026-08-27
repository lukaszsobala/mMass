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

# load libs
import json
import os.path
import xml.dom.minidom
import copy

# load modules
from . import config
import mspy

# MIGRATE PRE-7.0 XML LIBRARIES, THEN SEED ANY THAT ARE STILL MISSING
# -------------------------------------------------------------------
# Migration runs before seeding so a user's own edits are carried over rather
# than being masked by a freshly copied default.

# clear=False on purpose: mspy defines its libraries in code, and saveMonomers
# deliberately omits the "_InternalAA" residues that digestion and
# fragmentation depend on. Clearing here would drop them, and they would never
# come back from the migrated file. The replace= flags mirror what the pre-7.0
# startup used, so a migrated library merges exactly as it did before.
_XML_LOADERS = {
    "monomers": lambda path: mspy.loadMonomersXML(path, clear=False, replace=False),
    "modifications": lambda path: mspy.loadModificationsXML(
        path, clear=False, replace=True
    ),
    "enzymes": lambda path: mspy.loadEnzymesXML(path, clear=False, replace=True),
}

_JSON_SAVERS = {
    "monomers": mspy.saveMonomers,
    "modifications": mspy.saveModifications,
    "enzymes": mspy.saveEnzymes,
}

for _name in ("monomers", "modifications", "enzymes"):
    try:
        config.migrateLegacyLibrary(_name, _XML_LOADERS[_name], _JSON_SAVERS[_name])
    except Exception:
        pass

# Only the three mspy libraries are seeded here. The gui-side libraries
# (presets, references, compounds, mascot) are migrated and seeded further
# down, once their loaders are defined -- seeding them now would create the
# .json from the bundled default and make their migration a no-op, silently
# discarding the user's own library.
for _name in ("monomers", "modifications", "enzymes"):
    _target = config.getLibraryPath(_name)
    if not os.path.exists(_target):
        config.copy_default_config_file(_name + ".json", _target)


# LOAD USER'S LIBS INTO MSPY
# --------------------------

try:
    mspy.loadMonomers(config.getLibraryPath("monomers"), clear=False)
except Exception:
    mspy.saveMonomers(config.getLibraryPath("monomers"))

try:
    mspy.loadModifications(config.getLibraryPath("modifications"), clear=False)
except Exception:
    mspy.saveModifications(config.getLibraryPath("modifications"))

try:
    mspy.loadEnzymes(config.getLibraryPath("enzymes"), clear=False)
except Exception:
    mspy.saveEnzymes(config.getLibraryPath("enzymes"))


# INIT DEFAULT VALUES
# -------------------

presets = {
    "operator": {},
    "processing": {
        "ESI-ICR Peptides": {
            "crop": {
                "lowMass": 200,
                "highMass": 4000,
            },
            "baseline": {
                "precision": 15,
                "offset": 0.25,
            },
            "smoothing": {
                "method": "SG",
                "windowSize": 0.05,
                "cycles": 1,
            },
            "peakpicking": {
                "snThreshold": 4,
                "absIntThreshold": 0,
                "relIntThreshold": 0.001,
                "pickingHeight": 0.9,
                "baseline": 1,
                "smoothing": 0,
                "deisotoping": 1,
                "removeShoulders": 1,
            },
            "deisotoping": {
                "maxCharge": 5,
                "massTolerance": 0.005,
                "intTolerance": 0.5,
                "isotopeShift": 0.0,
                "removeIsotopes": 1,
                "removeUnknown": 1,
                "setAsMonoisotopic": 1,
                "labelEnvelope": "1st",
                "envelopeIntensity": "maximum",
                "convertToEnvelopes": 1,
            },
            "deconvolution": {
                "massType": 0,
                "groupWindow": 0.001,
                "groupPeaks": 1,
                "forceGroupWindow": 0,
            },
            "batch": {
                "math": 0,
                "crop": 0,
                "baseline": 0,
                "smoothing": 0,
                "peakpicking": 0,
                "deisotoping": 0,
                "deconvolution": 0,
            },
        },
        "MALDI-TOF Peptides": {
            "crop": {
                "lowMass": 750,
                "highMass": 4000,
            },
            "baseline": {
                "precision": 15,
                "offset": 0.25,
            },
            "smoothing": {
                "method": "SG",
                "windowSize": 0.2,
                "cycles": 2,
            },
            "peakpicking": {
                "snThreshold": 3.5,
                "absIntThreshold": 0,
                "relIntThreshold": 0.005,
                "pickingHeight": 0.75,
                "baseline": 1,
                "smoothing": 1,
                "deisotoping": 1,
                "removeShoulders": 0,
            },
            "deisotoping": {
                "maxCharge": 1,
                "massTolerance": 0.15,
                "intTolerance": 0.5,
                "isotopeShift": 0.0,
                "removeIsotopes": 1,
                "removeUnknown": 1,
                "setAsMonoisotopic": 1,
                "labelEnvelope": "1st",
                "envelopeIntensity": "maximum",
                "convertToEnvelopes": 1,
            },
            "deconvolution": {
                "massType": 0,
                "groupWindow": 0.05,
                "groupPeaks": 1,
                "forceGroupWindow": 0,
            },
            "batch": {
                "math": 0,
                "crop": 0,
                "baseline": 0,
                "smoothing": 0,
                "peakpicking": 0,
                "deisotoping": 0,
                "deconvolution": 0,
            },
        },
        "MALDI-TOF Proteins 5-20 kDa": {
            "crop": {
                "lowMass": 5000,
                "highMass": 20000,
            },
            "baseline": {
                "precision": 20,
                "offset": 0.25,
            },
            "smoothing": {
                "method": "MA",
                "windowSize": 5,
                "cycles": 2,
            },
            "peakpicking": {
                "snThreshold": 2.5,
                "absIntThreshold": 0,
                "relIntThreshold": 0.01,
                "pickingHeight": 0.75,
                "baseline": 1,
                "smoothing": 1,
                "deisotoping": 0,
                "removeShoulders": 0,
            },
            "deisotoping": {
                "maxCharge": 1,
                "massTolerance": 0.1,
                "intTolerance": 0.5,
                "isotopeShift": 0.0,
                "removeIsotopes": 0,
                "removeUnknown": 0,
                "setAsMonoisotopic": 0,
                "labelEnvelope": "1st",
                "envelopeIntensity": "maximum",
                "convertToEnvelopes": 1,
            },
            "deconvolution": {
                "massType": 1,
                "groupWindow": 2.5,
                "groupPeaks": 1,
                "forceGroupWindow": 0,
            },
            "batch": {
                "math": 0,
                "crop": 0,
                "baseline": 0,
                "smoothing": 0,
                "peakpicking": 0,
                "deisotoping": 0,
                "deconvolution": 0,
            },
        },
        "MALDI-TOF PSD": {
            "crop": {
                "lowMass": 0,
                "highMass": 4000,
            },
            "baseline": {
                "precision": 20,
                "offset": 0.25,
            },
            "smoothing": {
                "method": "SG",
                "windowSize": 0.25,
                "cycles": 2,
            },
            "peakpicking": {
                "snThreshold": 3,
                "absIntThreshold": 0,
                "relIntThreshold": 0.005,
                "pickingHeight": 0.75,
                "baseline": 1,
                "smoothing": 1,
                "deisotoping": 1,
                "removeShoulders": 0,
            },
            "deisotoping": {
                "maxCharge": 1,
                "massTolerance": 0.2,
                "intTolerance": 0.5,
                "isotopeShift": 0.0,
                "removeIsotopes": 1,
                "removeUnknown": 0,
                "setAsMonoisotopic": 1,
                "labelEnvelope": "1st",
                "envelopeIntensity": "maximum",
                "convertToEnvelopes": 1,
            },
            "deconvolution": {
                "massType": 0,
                "groupWindow": 0.1,
                "groupPeaks": 1,
                "forceGroupWindow": 0,
            },
            "batch": {
                "math": 0,
                "crop": 0,
                "baseline": 0,
                "smoothing": 0,
                "peakpicking": 0,
                "deisotoping": 0,
                "deconvolution": 0,
            },
        },
        "MALDI-ICR Peptides": {
            "crop": {
                "lowMass": 750,
                "highMass": 4000,
            },
            "baseline": {
                "precision": 15,
                "offset": 0.25,
            },
            "smoothing": {
                "method": "SG",
                "windowSize": 0.05,
                "cycles": 1,
            },
            "peakpicking": {
                "snThreshold": 4,
                "absIntThreshold": 0,
                "relIntThreshold": 0.001,
                "pickingHeight": 0.9,
                "baseline": 1,
                "smoothing": 0,
                "deisotoping": 1,
                "removeShoulders": 1,
            },
            "deisotoping": {
                "maxCharge": 1,
                "massTolerance": 0.02,
                "intTolerance": 0.5,
                "isotopeShift": 0.0,
                "removeIsotopes": 1,
                "removeUnknown": 1,
                "setAsMonoisotopic": 1,
                "labelEnvelope": "1st",
                "envelopeIntensity": "maximum",
                "convertToEnvelopes": 1,
            },
            "deconvolution": {
                "massType": 0,
                "groupWindow": 0.001,
                "groupPeaks": 1,
                "forceGroupWindow": 0,
            },
            "batch": {
                "math": 0,
                "crop": 0,
                "baseline": 0,
                "smoothing": 0,
                "peakpicking": 0,
                "deisotoping": 0,
                "deconvolution": 0,
            },
        },
        "MALDI-ICR Low Mass": {
            "crop": {
                "lowMass": 200,
                "highMass": 1500,
            },
            "baseline": {
                "precision": 15,
                "offset": 0.25,
            },
            "smoothing": {
                "method": "SG",
                "windowSize": 0.05,
                "cycles": 1,
            },
            "peakpicking": {
                "snThreshold": 6,
                "absIntThreshold": 0,
                "relIntThreshold": 0.001,
                "pickingHeight": 0.9,
                "baseline": 1,
                "smoothing": 0,
                "deisotoping": 1,
                "removeShoulders": 1,
            },
            "deisotoping": {
                "maxCharge": 1,
                "massTolerance": 0.02,
                "intTolerance": 0.7,
                "isotopeShift": 0.0,
                "removeIsotopes": 1,
                "removeUnknown": 1,
                "setAsMonoisotopic": 1,
                "labelEnvelope": "1st",
                "envelopeIntensity": "maximum",
                "convertToEnvelopes": 1,
            },
            "deconvolution": {
                "massType": 0,
                "groupWindow": 0.001,
                "groupPeaks": 1,
                "forceGroupWindow": 0,
            },
            "batch": {
                "math": 0,
                "crop": 0,
                "baseline": 0,
                "smoothing": 0,
                "peakpicking": 0,
                "deisotoping": 0,
                "deconvolution": 0,
            },
        },
    },
    "modifications": {
        "-None-": [],
        "Carbamidomethyl (C)": [
            ["Carbamidomethyl", "C", "f"],
        ],
        "Oxidation (MW)": [
            ["Oxidation", "M", "v"],
            ["Oxidation", "W", "v"],
        ],
        "N-Formyl Met": [["FormylMet", 0, "v"]],
    },
    "fragments": {
        "-None-": [],
        "CID": ["b", "y", "-NH3", "-H2O"],
        "ECD/ETD": ["c", "y"],
        "ISD": ["a", "c", "y"],
        "PSD": ["a", "b", "y", "-NH3", "-H2O", "im"],
        "Ladder-N": ["n-ladder"],
        "Ladder-C": ["c-ladder"],
    },
}

references = {
    "Trypsin (Porcine) - MALDI Pos Mo": [
        ("Trypsin (108-115) [M+H]+", 842.5094),
        ("Trypsin (209-216) [M+H]+", 906.5044),
        ("Trypsin (1-8) [M+H]+", 952.3894),
        ("Trypsin (148-157) [M+H]+", 1006.4874),
        ("Trypsin (98-107) [M+H]+", 1045.5637),
        ("Trypsin (134-147) [M+H]+", 1469.7305),
        ("Trypsin (58-72) [M+H]+", 1713.8084),
        ("Trypsin (217-231) [M+H]+", 1736.8425),
        ("Trypsin (116-133) [M+H]+", 1768.7993),
        ("Trypsin (62-77) [M+H]+", 1774.8975),
        ("Trypsin (58-76) [M+H]+", 2083.0096),
        ("Trypsin (158-178) [M+H]+", 2158.0307),
        ("Trypsin (58-77) [M+H]+", 2211.1040),
        ("Trypsin (78-97) [M+H]+", 2283.1802),
        ("Trypsin (179-208) [M+H]+", 3013.3237),
    ],
    "HCCA Clusters - MALDI Pos Mo": [
        ("HCCA [M+H-H2O]+", 172.039304),
        ("HCCA [M+H]+", 190.049869),
        ("HCCA [M+Na-H2O]+", 194.021249),
        ("HCCA [M+Na]+", 212.031814),
        ("HCCA [M+K-H2O]+", 209.995186),
        ("HCCA [M+K]+", 228.005751),
        ("HCCA [2M+H-H2O]+", 361.081897),
        ("HCCA [2M+H]+", 379.092462),
        ("HCCA [2M+Na-H2O]+", 383.063842),
        ("HCCA [2M+Na]+", 401.074407),
        ("HCCA [2M+K-H2O]+", 399.037779),
        ("HCCA [2M+K]+", 417.048344),
        ("HCCA [2M+K+Na-H2O]+", 422.027),
        ("HCCA [3M+H-H2O]+", 550.12449),
        ("HCCA [3M+H]+", 568.135055),
        ("HCCA [3M+Na-H2O]+", 572.106435),
        ("HCCA [3M+Na]+", 590.117),
        ("HCCA [3M+K-H2O]+", 588.080372),
        ("HCCA [3M+K]+", 606.090937),
        ("HCCA [3M+K+Na-H2O]+", 611.069593),
        ("HCCA [4M+H-H2O]+", 739.167083),
        ("HCCA [4M+H]+", 757.177648),
        ("HCCA [4M+Na-H2O]+", 761.149028),
        ("HCCA [4M+Na]+", 779.159593),
        ("HCCA [4M+K-H2O]+", 777.122965),
        ("HCCA [4M+K]+", 795.13353),
        ("HCCA [4M+K+Na-H2O]+", 800.112186),
        ("HCCA [5M+H-H2O]+", 928.209676),
        ("HCCA [5M+H]+", 946.220241),
        ("HCCA [5M+Na-H2O]+", 950.191621),
        ("HCCA [5M+Na]+", 968.202186),
        ("HCCA [5M+K-H2O]+", 966.165558),
        ("HCCA [5M+K]+", 984.176123),
        ("HCCA [5M+K+Na-H2O]+", 989.154779),
        ("HCCA [6M+H-H2O]+", 1117.252269),
        ("HCCA [6M+H]+", 1135.262834),
        ("HCCA [6M+Na-H2O]+", 1139.234214),
        ("HCCA [6M+Na]+", 1157.244779),
        ("HCCA [6M+K-H2O]+", 1155.208151),
        ("HCCA [6M+K]+", 1173.218716),
        ("HCCA [6M+K+Na-H2O]+", 1178.197372),
        ("HCCA [7M+H-H2O]+", 1306.294862),
        ("HCCA [7M+H]+", 1324.305427),
        ("HCCA [7M+Na-H2O]+", 1328.276807),
        ("HCCA [7M+Na]+", 1346.287372),
        ("HCCA [7M+K-H2O]+", 1344.250744),
        ("HCCA [7M+K]+", 1362.261309),
        ("HCCA [7M+K+Na-H2O]+", 1367.239965),
    ],
    "DHB Clusters - MALDI Pos Mo": [
        ("DHB [M+H-H2O]+", 137.02332),
        ("DHB [M+H]+", 155.033885),
        ("DHB [M+Na-H2O]+", 159.005265),
        ("DHB [M+Na]+", 177.01583),
        ("DHB [M+K-H2O]+", 174.979202),
        ("DHB [M+K]+", 192.989767),
        ("DHB [2M+H-2H2O]+", 273.039364),
        ("DHB [2M+H-H2O]+", 291.049929),
        ("DHB [2M+H]+", 309.060494),
        ("DHB [2M+Na-2H2O]+", 295.021309),
        ("DHB [2M+Na-H2O]+", 313.031874),
        ("DHB [2M+Na]+", 331.042439),
        ("DHB [2M+K-H2O]+", 329.005811),
        ("DHB [2M+K]+", 347.016376),
        ("DHB [2M+K+Na-H2O]+", 351.995032),
        ("DHB [3M+H-3H2O]+", 409.055408),
        ("DHB [3M+H-H2O]+", 445.076538),
        ("DHB [3M+H]+", 463.087103),
        ("DHB [3M+Na-3H2O]+", 431.037353),
        ("DHB [3M+Na-H2O]+", 467.058483),
        ("DHB [3M+Na]+", 485.069048),
        ("DHB [3M+K-H2O]+", 483.03242),
        ("DHB [3M+K]+", 501.042985),
        ("DHB [3M+K+Na-H2O]+", 506.021641),
        ("DHB [4M+H-4H2O]+", 545.071452),
        ("DHB [4M+H-H2O]+", 599.103147),
        ("DHB [4M+H]+", 617.113712),
        ("DHB [4M+Na-4H2O]+", 567.053397),
        ("DHB [4M+Na-H2O]+", 621.085092),
        ("DHB [4M+Na]+", 639.095657),
        ("DHB [4M+K-H2O]+", 637.059029),
        ("DHB [4M+K]+", 655.069594),
        ("DHB [4M+K+Na-H2O]+", 660.04825),
        ("DHB [5M+H-5H2O]+", 681.087496),
        ("DHB [5M+H-H2O]+", 753.129756),
        ("DHB [5M+H]+", 771.140321),
        ("DHB [5M+Na-H2O]+", 775.111701),
        ("DHB [5M+Na]+", 793.122266),
        ("DHB [5M+K-H2O]+", 791.085638),
        ("DHB [5M+K]+", 809.096203),
        ("DHB [5M+K+Na-H2O]+", 814.074859),
        ("DHB [6M+H-6H2O]+", 817.103540),
        ("DHB [6M+H-H2O]+", 907.156365),
        ("DHB [6M+H]+", 925.16693),
        ("DHB [6M+Na-H2O]+", 929.13831),
        ("DHB [6M+Na]+", 947.148875),
        ("DHB [6M+K-H2O]+", 945.112247),
        ("DHB [6M+K]+", 963.122812),
        ("DHB [6M+K+Na-H2O]+", 968.101468),
        ("DHB [7M+H-7H2O]+", 953.119584),
        ("DHB [7M+H-H2O]+", 1061.182974),
        ("DHB [7M+H]+", 1079.193539),
        ("DHB [7M+Na-H2O]+", 1083.164919),
        ("DHB [7M+Na]+", 1101.175484),
        ("DHB [7M+K-H2O]+", 1099.138856),
        ("DHB [7M+K]+", 1117.149421),
        ("DHB [7M+K+Na-H2O]+", 1122.128077),
    ],
    "In-Gel (Trypsin) - MALDI Pos Mo": [
        ("Keratin 10 [M+H]+", 1165.5853),
        ("Keratin 1/II [M+H]+", 1179.6010),
        ("Keratin 1/II [M+H]+", 1300.5302),
        ("Keratin 1/II [M+H]+", 1716.8517),
        ("Keratin 1/II [M+H]+", 1993.9767),
        ("Keratin 1 [M+H]+", 2383.9520),
        ("Keratin 10 [M+H]+", 2825.4056),
        ("Trypsin (108-115) [M+H]+", 842.5094),
        ("Trypsin (209-216) [M+H]+", 906.5044),
        ("Trypsin (1-8) [M+H]+", 952.3894),
        ("Trypsin (148-157) [M+H]+", 1006.4874),
        ("Trypsin (98-107) [M+H]+", 1045.5637),
        ("Trypsin (134-147) [M+H]+", 1469.7305),
        ("Trypsin (58-72) [M+H]+", 1713.8084),
        ("Trypsin (217-231) [M+H]+", 1736.8425),
        ("Trypsin (116-133) [M+H]+", 1768.7993),
        ("Trypsin (62-77) [M+H]+", 1774.8975),
        ("Trypsin (58-76) [M+H]+", 2083.0096),
        ("Trypsin (158-178) [M+H]+", 2158.0307),
        ("Trypsin (58-77) [M+H]+", 2211.1040),
        ("Trypsin (78-97) [M+H]+", 2283.1802),
        ("Trypsin (179-208) [M+H]+", 3013.3237),
    ],
}

compounds = {}

mascot = {
    "Matrix Science": {
        "protocol": "http",
        "host": "www.matrixscience.com",
        "path": "/",
        "search": "cgi/nph-mascot.exe",
        "results": "cgi/master_results.pl",
        "export": "cgi/export_dat_2.pl",
        "params": "cgi/get_params.pl",
    },
}


# LOAD FUNCTIONS
# --------------


def loadPresetsXML(
    path=config.getLegacyLibraryPath("presets"), clear=True, replace=True  # noqa: B008
):
    """Parse processing presets XML and get data."""

    container = {}

    # parse XML
    document = xml.dom.minidom.parse(path)

    # get operator presets
    operatorTags = document.getElementsByTagName("operator")
    if operatorTags:
        presetsTags = operatorTags[0].getElementsByTagName("presets")
        if presetsTags:
            container["operator"] = {}

            for presetsTag in presetsTags:
                name = presetsTag.getAttribute("name")
                container["operator"][name] = {
                    "operator": "",
                    "contact": "",
                    "institution": "",
                    "instrument": "",
                }
                _getParams(presetsTag, container["operator"][name])

    # get processing presets
    processingTags = document.getElementsByTagName("processing")
    if processingTags:
        presetsTags = processingTags[0].getElementsByTagName("presets")
        if presetsTags:
            container["processing"] = {}

            for presetsTag in presetsTags:
                name = presetsTag.getAttribute("name")
                container["processing"][name] = copy.deepcopy(config.processing)

                cropTags = presetsTag.getElementsByTagName("crop")
                if cropTags:
                    _getParams(cropTags[0], container["processing"][name]["crop"])

                baselineTags = presetsTag.getElementsByTagName("baseline")
                if baselineTags:
                    _getParams(
                        baselineTags[0], container["processing"][name]["baseline"]
                    )

                smoothingTags = presetsTag.getElementsByTagName("smoothing")
                if smoothingTags:
                    _getParams(
                        smoothingTags[0], container["processing"][name]["smoothing"]
                    )

                peakpickingTags = presetsTag.getElementsByTagName("peakpicking")
                if peakpickingTags:
                    _getParams(
                        peakpickingTags[0], container["processing"][name]["peakpicking"]
                    )

                deisotopingTags = presetsTag.getElementsByTagName("deisotoping")
                if deisotopingTags:
                    _getParams(
                        deisotopingTags[0], container["processing"][name]["deisotoping"]
                    )

                deconvolutionTags = presetsTag.getElementsByTagName("deconvolution")
                if deconvolutionTags:
                    _getParams(
                        deconvolutionTags[0],
                        container["processing"][name]["deconvolution"],
                    )

                batchTags = presetsTag.getElementsByTagName("batch")
                if batchTags:
                    _getParams(batchTags[0], container["processing"][name]["batch"])

    # get modifications presets
    modificationsTags = document.getElementsByTagName("modifications")
    if modificationsTags:
        presetsTags = modificationsTags[0].getElementsByTagName("presets")
        if presetsTags:
            container["modifications"] = {}

            for presetsTag in presetsTags:
                name = presetsTag.getAttribute("name")
                container["modifications"][name] = []

                modificationTags = presetsTag.getElementsByTagName("modification")
                for modificationTag in modificationTags:
                    modName = modificationTag.getAttribute("name")
                    modPosition = modificationTag.getAttribute("position")
                    modType = modificationTag.getAttribute("type")
                    container["modifications"][name].append(
                        [modName, modPosition, modType]
                    )

    # get fragments presets
    fragmentsTags = document.getElementsByTagName("fragments")
    if fragmentsTags:
        presetsTags = fragmentsTags[0].getElementsByTagName("presets")
        if presetsTags:
            container["fragments"] = {}

            for presetsTag in presetsTags:
                name = presetsTag.getAttribute("name")
                container["fragments"][name] = []

                fragmentTags = presetsTag.getElementsByTagName("fragment")
                for fragmentTag in fragmentTags:
                    fragName = fragmentTag.getAttribute("name")
                    container["fragments"][name].append(fragName)

    # update current lib
    for group in container:
        if container[group] and clear:
            presets[group].clear()
        for key in container[group]:
            if replace or key not in presets[group]:
                presets[group][key] = container[group][key]


# ----


def loadReferencesXML(path=config.getLegacyLibraryPath("references"), clear=True):  # noqa: B008
    """Parse calibration references XML and get data."""

    container = {}

    # parse XML
    document = xml.dom.minidom.parse(path)

    # get references
    groupTags = document.getElementsByTagName("group")
    if groupTags:
        for groupTag in groupTags:
            groupName = groupTag.getAttribute("name")
            container[groupName] = []

            referenceTags = groupTag.getElementsByTagName("reference")
            if referenceTags:
                for referenceTag in referenceTags:
                    name = referenceTag.getAttribute("name")
                    mass = referenceTag.getAttribute("mass")
                    container[groupName].append((name, float(mass)))

    # update current lib
    if container and clear:
        references.clear()
    for group in container:
        references[group] = container[group]


# ----


def loadCompoundsXML(path=config.getLegacyLibraryPath("compounds"), clear=True):  # noqa: B008
    """Parse compounds XML and get data."""

    container = {}

    # parse XML
    document = xml.dom.minidom.parse(path)

    # get references
    groupTags = document.getElementsByTagName("group")
    if groupTags:
        for groupTag in groupTags:
            groupName = groupTag.getAttribute("name")
            container[groupName] = {}

            compoundTags = groupTag.getElementsByTagName("compound")
            if compoundTags:
                for compoundTag in compoundTags:
                    try:
                        name = compoundTag.getAttribute("name")
                        compound = mspy.compound(compoundTag.getAttribute("formula"))
                        compound.description = _getNodeText(compoundTag)
                        container[groupName][name] = compound
                    except Exception:
                        pass

    # update current lib
    if container and clear:
        compounds.clear()
    for group in container:
        compounds[group] = container[group]


# ----


def loadMascotXML(
    path=config.getLegacyLibraryPath("mascot"), clear=True, replace=True  # noqa: B008
):
    """Parse mascot servers XML and get data."""

    container = {}

    # parse XML
    document = xml.dom.minidom.parse(path)

    # get references
    serverTags = document.getElementsByTagName("server")
    if serverTags:
        for serverTag in serverTags:
            name = serverTag.getAttribute("name")
            container[name] = {
                "protocol": "http",
                "host": "",
                "path": "/",
                "search": "cgi/nph-mascot.exe",
                "results": "cgi/master_results.pl",
                "export": "cgi/export_dat_2.pl",
                "params": "cgi/get_params.pl",
            }
            _getParams(serverTag, container[name])

    # update current lib
    if container and clear:
        mascot.clear()
    for server in container:
        mascot[server] = container[server]


# ----


def _getParams(sectionTag, section):
    """Get params from nodes."""

    if sectionTag:
        paramTags = sectionTag.getElementsByTagName("param")
        if paramTags:
            for paramTag in paramTags:
                name = paramTag.getAttribute("name")
                valueType = paramTag.getAttribute("type")
                if name in section and valueType in ("unicode", "str", "float", "int"):
                    try:
                        value = paramTag.getAttribute("value")
                        if valueType in ("unicode", "str"):
                            section[name] = value
                        elif valueType == "float":
                            section[name] = float(value)
                        elif valueType == "int":
                            section[name] = int(value)
                    except Exception:
                        pass


# ----


def _getNodeText(node):
    """Get text from node list."""

    buff = ""
    for child in node.childNodes:
        if child.nodeType == child.TEXT_NODE:
            buff += child.data

    return buff


# ----


# SAVE FUNCTIONS
# --------------


def savePresets(path=None):
    """Serialize the presets library to JSON."""

    if path is None:
        path = config.getLibraryPath("presets")

    data = {
        "operator": {
            name: dict(item) for name, item in sorted(presets["operator"].items())
        },
        "processing": {
            name: config._plainCopy(item)
            for name, item in sorted(presets["processing"].items())
        },
        "modifications": {
            name: [list(mod) for mod in item]
            for name, item in sorted(presets["modifications"].items())
        },
        "fragments": {
            name: list(item) for name, item in sorted(presets["fragments"].items())
        },
    }

    return _writeJSON(path, {"schemaVersion": 1, "presets": data})


def loadPresets(path=None, clear=True, replace=True):
    """Read a JSON presets library."""

    if path is None:
        path = config.getLibraryPath("presets")

    data = _readJSON(path, "presets")
    container = {}

    operator = data.get("operator")
    if isinstance(operator, dict):
        container["operator"] = {}
        for name, item in operator.items():
            entry = {"operator": "", "contact": "", "institution": "", "instrument": ""}
            if isinstance(item, dict):
                for key in entry:
                    if isinstance(item.get(key), str):
                        entry[key] = item[key]
            container["operator"][name] = entry

    processing = data.get("processing")
    if isinstance(processing, dict):
        container["processing"] = {}
        for name, item in processing.items():
            merged = copy.deepcopy(config.processing)
            if isinstance(item, dict):
                config._mergeSection(merged, item, "processing")
            container["processing"][name] = merged

    modifications = data.get("modifications")
    if isinstance(modifications, dict):
        container["modifications"] = {
            name: [list(mod) for mod in item if isinstance(mod, (list, tuple))]
            for name, item in modifications.items()
            if isinstance(item, list)
        }

    fragments = data.get("fragments")
    if isinstance(fragments, dict):
        container["fragments"] = {
            name: [str(f) for f in item]
            for name, item in fragments.items()
            if isinstance(item, list)
        }

    for group in container:
        if container[group] and clear:
            presets[group].clear()
        for key in container[group]:
            if replace or key not in presets[group]:
                presets[group][key] = container[group][key]


# ----


def saveReferences(path=None):
    """Serialize the calibration references library to JSON."""

    if path is None:
        path = config.getLibraryPath("references")

    data = {
        group: [[ref[0], float(ref[1])] for ref in references[group]]
        for group in sorted(references.keys())
    }

    return _writeJSON(path, {"schemaVersion": 1, "references": data})


def loadReferences(path=None, clear=True):
    """Read a JSON calibration references library."""

    if path is None:
        path = config.getLibraryPath("references")

    container = {}
    for group, items in _readJSON(path, "references").items():
        if not isinstance(items, list):
            continue
        entries = []
        for ref in items:
            if isinstance(ref, (list, tuple)) and len(ref) >= 2:
                try:
                    entries.append((str(ref[0]), float(ref[1])))
                except (TypeError, ValueError):
                    pass
        container[group] = entries

    if container and clear:
        references.clear()
    for group in container:
        references[group] = container[group]


# ----


def saveCompounds(path=None):
    """Serialize the compounds library to JSON."""

    if path is None:
        path = config.getLibraryPath("compounds")

    data = {}
    for group in sorted(compounds.keys()):
        data[group] = {
            name: {
                "formula": compound.expression,
                "description": compound.description,
            }
            for name, compound in sorted(compounds[group].items())
        }

    return _writeJSON(path, {"schemaVersion": 1, "compounds": data})


def loadCompounds(path=None, clear=True):
    """Read a JSON compounds library."""

    if path is None:
        path = config.getLibraryPath("compounds")

    container = {}
    for group, items in _readJSON(path, "compounds").items():
        if not isinstance(items, dict):
            continue
        container[group] = {}
        for name, item in items.items():
            if not isinstance(item, dict):
                continue
            try:
                compound = mspy.compound(item.get("formula", ""))
                compound.description = item.get("description", "")
                container[group][name] = compound
            except Exception:
                pass

    if container and clear:
        compounds.clear()
    for group in container:
        compounds[group] = container[group]


# ----


_MASCOT_SERVER_DEFAULTS = {
    "protocol": "http",
    "host": "",
    "path": "/",
    "search": "cgi/nph-mascot.exe",
    "results": "cgi/master_results.pl",
    "export": "cgi/export_dat_2.pl",
    "params": "cgi/get_params.pl",
}


def saveMascot(path=None):
    """Serialize the Mascot server library to JSON."""

    if path is None:
        path = config.getLibraryPath("mascot")

    data = {
        name: {key: mascot[name].get(key, default) for key, default in _MASCOT_SERVER_DEFAULTS.items()}
        for name in sorted(mascot.keys())
    }

    return _writeJSON(path, {"schemaVersion": 1, "mascot": data})


def loadMascot(path=None, clear=True, replace=True):
    """Read a JSON Mascot server library."""

    if path is None:
        path = config.getLibraryPath("mascot")

    container = {}
    for name, item in _readJSON(path, "mascot").items():
        if not isinstance(item, dict):
            continue
        entry = dict(_MASCOT_SERVER_DEFAULTS)
        for key in entry:
            if isinstance(item.get(key), str):
                entry[key] = item[key]
        container[name] = entry

    if container and clear:
        mascot.clear()
    for name in container:
        if replace or name not in mascot:
            mascot[name] = container[name]


# ----


def _readJSON(path, section):
    """Return one section of a library file."""

    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)

    if not isinstance(data, dict):
        raise ValueError("%s: root must be a JSON object" % path)

    entries = data.get(section)
    if not isinstance(entries, dict):
        raise ValueError("%s: missing '%s' object" % (path, section))

    return entries


def _writeJSON(path, data):
    """Serialize a library payload atomically."""

    try:
        encoded = json.dumps(data, indent=2, ensure_ascii=False)
    except (TypeError, ValueError):
        return False

    return config.write_file_atomically(path, (encoded + "\n").encode("utf-8"))


# ----


def _escape(text):
    """Clear special characters such as <> etc."""

    text = text.strip()
    search = ("&", '"', "'", "<", ">")
    replace = ("&amp;", "&quot;", "&apos;", "&lt;", "&gt;")
    for x, item in enumerate(search):
        text = text.replace(item, replace[x])

    return text


# ----


# MIGRATE AND LOAD GUI LIBS
# -------------------------

for _name, _readXML, _saveJSON in (
    ("presets", lambda path: loadPresetsXML(path, clear=True), savePresets),
    ("references", lambda path: loadReferencesXML(path, clear=True), saveReferences),
    ("compounds", lambda path: loadCompoundsXML(path, clear=True), saveCompounds),
    ("mascot", lambda path: loadMascotXML(path, clear=True), saveMascot),
):
    try:
        config.migrateLegacyLibrary(_name, _readXML, _saveJSON)
    except Exception:
        pass
    if not os.path.exists(config.getLibraryPath(_name)):
        config.copy_default_config_file(
            _name + ".json", config.getLibraryPath(_name)
        )

try:
    loadPresets()
except Exception:
    savePresets()

try:
    loadReferences()
except Exception:
    saveReferences()

try:
    loadCompounds()
except Exception:
    saveCompounds()

try:
    loadMascot()
except Exception:
    saveMascot()
