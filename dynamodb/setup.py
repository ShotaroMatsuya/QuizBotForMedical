from setuptools import setup

setup(
    name="cli-tools",
    version="1.0",
    py_modules=["csv_import"],
    install_requires=["boto3", "click", "tqdm"],
    entry_points={
        "console_scripts": ["import_csv=csv_import:cmd", "import_json=json_import:cmd"]
    },  # greetingsコマンド=greeterモジュールのgreetメソッド
)
