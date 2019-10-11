# Variables
SOURCE = minet

# Functions
define clean
	rm -rf *.egg-info .pytest_cache build dist
	find . -name "*.pyc" | xargs rm -f
	find . -name __pycache__ | xargs rm -rf
	rm -rf ftest/content
	rm -f *.spec
endef

# Targets
all: lint test
compile: clean pyinstaller
test: unit
publish: clean lint test upload
	$(call clean)

clean:
	$(call clean)

deps:
	find ./requirements -name "*.txt" | xargs -n 1 pip3 install -r

lint:
	@echo Linting source code using pep8...
	pycodestyle --ignore E501,E722,E741,W503,W504 $(SOURCE) test
	@echo
	@echo Searching for unused imports...
	importchecker $(SOURCE) | grep -v __init__ | grep -v dragnet | grep -v encodings.idna || true
	@echo

readme:
	python -m scripts.generate_readme > README.md

unit:
	@echo Running unit tests...
	pytest -svvv
	@echo

upload:
	python setup.py sdist bdist_wheel
	twine upload dist/*

pyinstaller: clean
	./scripts/pyinstaller.sh
