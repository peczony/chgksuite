from setuptools import setup


def get_version():
    version = {}
    with open("chgksuite/version.py") as f:
        exec(f.read(), version)
    return version["__version__"]


setup(
    name="chgksuite",
    version=get_version(),
    author="Alexander Pecheny",
    author_email="peczony@gmail.com",
    description="A package for chgk automation",
    url="https://gitlab.com/peczony/chgksuite",
    classifiers=[
        "Programming Language :: Python :: 3",
        "License :: OSI Approved :: MIT License",
        "Operating System :: OS Independent",
    ],
    packages=["chgksuite"],
    package_data={
        "chgksuite": [
            "resources/*.json",
            "resources/*.docx",
            "resources/*.tex",
            "resources/*.sty",
        ]
    },
    entry_points={"console_scripts": ["chgksuite = chgksuite.__main__:main"]},
)
