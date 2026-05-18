import sys
import numpy
from setuptools import setup
from setuptools import Extension

numpyInclude = numpy.get_include()
pythonInclude = sys.prefix + "/include"


def build(setup_kwargs):
    # Extension build code removed
    pass
