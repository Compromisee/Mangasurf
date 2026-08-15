from setuptools import setup, find_packages

setup(
    name="mangasurf",
    version="1.2.0",
    description="Download manga, manhwa and manhua from 23+ sites as CBZ, PDF or EPUB - CLI, menu, TUI, PyQt and GUI reader",
    packages=find_packages(),
    include_package_data=True,
    package_data={
        "readerm.reader": [
            "app/*",
            "app/**/*",
            "foliate/*",
            "foliate/vendor/*",
            "foliate/vendor/pdfjs/*",
            "foliate/vendor/pdfjs/**/*",
        ],
    },
    install_requires=[
        "requests>=2.31",
        "beautifulsoup4>=4.12",
        "rich>=13.0",
        "Pillow>=10.0",
        "fpdf2>=2.7",
        "EbookLib>=0.18",
        "PyQt6>=6.5.0",
    ],
    extras_require={
        "gui": ["PyQt6>=6.5.0", "pywebview>=5.0"],
        "tui": ["textual>=0.60"],
        "tray": ["pystray>=0.19", "Pillow>=10.0"],
        "server": ["flask>=3.0"],
        "all": ["PyQt6>=6.5.0", "pywebview>=5.0", "textual>=0.60", "pystray>=0.19", "flask>=3.0"],
    },
    entry_points={
        "console_scripts": [
            "mangasurf=readerm.cli:main",
            "mangasurf-gui=readerm.gui:run_gui",
            "readerm=readerm.cli:main",
            "readerm-gui=readerm.gui:run_gui",
        ],
    },
    python_requires=">=3.9",
)
