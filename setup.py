from pathlib import Path

from setuptools import find_packages, setup

this_directory = Path(__file__).parent
long_description = (this_directory / 'README.md').read_text()

girder_version = '5.0.6'

setup(
    name='girder-collection-review',
    long_description=long_description,
    long_description_content_type='text/markdown',
    version='1.0.0',
    description=(
        'Girder plugin to share a collection with anonymous reviewers via a revocable access key'
    ),
    packages=find_packages(),
    include_package_data=True,
    license='BSD-3-Clause',
    classifiers=[
        'Development Status :: 4 - Beta',
        'Environment :: Web Environment',
        'License :: OSI Approved :: BSD License',
        'Operating System :: POSIX :: Linux',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
    ],
    python_requires='>=3.10',
    setup_requires=['setuptools-git'],
    install_requires=[
        f'girder>={girder_version}',
    ],
    entry_points={
        'girder.plugin': ['collection_review = girder_collection_review:CollectionReviewPlugin'],
    },
    zip_safe=False,
)
