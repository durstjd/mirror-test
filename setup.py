"""
Setup script for Mirror Test modular package.
"""

from setuptools import setup, find_packages

setup(
    name="mirror-test",
    version="2.2.0",
    description="A secure web interface for testing Linux repository mirrors using container builds",
    author="Mirror Test Team",
    packages=find_packages(),
    python_requires=">=3.8",
    install_requires=[
        "PyYAML>=5.4.0",
    ],
    extras_require={
        "web": [
            "flask>=2.0.0",
            "flask-limiter>=2.0.0",
            "flask-wtf>=1.0.0",
            "flask-cors>=3.0.0",
        ],
        "ldap": [
            "python-ldap>=3.4.0",
        ],
        "all": [
            "flask>=2.0.0",
            "flask-limiter>=2.0.0",
            "flask-wtf>=1.0.0",
            "flask-cors>=3.0.0",
            "python-ldap>=3.4.0",
        ]
    },
    entry_points={
        "console_scripts": [
            "mirror-test=mirror_test.main:main",
        ],
    },
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: System Administrators",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "Programming Language :: Python :: 3.11",
        "Programming Language :: Python :: 3.12",
        "Topic :: System :: Systems Administration",
        "Topic :: Internet :: WWW/HTTP :: Dynamic Content",
    ],
)
