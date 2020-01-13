from setuptools import setup

setup(
    name="chgksuite",
    version="0.6",
    packages=["chgksuite"],
    entry_points={
        "console_scripts": ["chgksuite = chgksuite.__main__:main"]
    },
    include_package_data=True
)
