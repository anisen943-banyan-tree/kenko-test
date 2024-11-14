from setuptools import setup, find_packages

setup(
    name="document-processing",
    version="0.1",
    packages=find_packages(where="document-processing/src"),
    package_dir={"": "document-processing/src"},
    python_requires=">=3.8",
)