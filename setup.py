from setuptools import setup

setup(
    name="chgksuite",
    version="0.6.0",
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
