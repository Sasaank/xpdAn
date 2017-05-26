from setuptools import setup, find_packages

setup(
    name='xpdan',
    version='0.1.2',
    packages=find_packages(),
    description='data processing module',
    zip_safe=False,
    package_data={'xpdan': ['config/*']},
    include_package_data=True,
    url='http:/github.com/xpdAcq/xpdAn'
)
