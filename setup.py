from setuptools import setup, find_packages

setup(
    name='scaler-pics',
    version='0.1.1',
    description='A Python library for image scaling and conversion',
    long_description=open('README.md').read(),
    long_description_content_type='text/markdown',
    author='Matej Ukmar',
    author_email='matejukmar@gmail.com',
    url='https://github.com/scaler-pics/scaler.pics-py',
    packages=find_packages(),
    install_requires=[
        'requests',
        'aiohttp',
        'PyJWT',
    ],
    classifiers=[
        'Programming Language :: Python :: 3',
        'License :: OSI Approved :: MIT License',
        'Operating System :: OS Independent',
    ],
    python_requires='>=3.6',
)
