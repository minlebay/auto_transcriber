PACKAGE  := auto-transcriber
VERSION  := 1.0.0
ARCH     := amd64
DEB_FILE := $(PACKAGE)_$(VERSION)_$(ARCH).deb
PYTHON   := venv/bin/python

.PHONY: all venv gen-icons run deb build-deps clean distclean install

all: gen-icons

venv: venv/bin/python

venv/bin/python:
	python3 -m venv --system-site-packages venv
	venv/bin/pip install --quiet --upgrade pip
	venv/bin/pip install --quiet -r requirements.txt

gen-icons: venv
	$(PYTHON) icons/generate.py

run: gen-icons
	PYTHONPATH=. $(PYTHON) main.py

build-deps:
	sudo apt-get install -y debhelper

deb: gen-icons
	@which dh > /dev/null 2>&1 || (echo "debhelper not found — run: make build-deps" && exit 1)
	ln -sfn packaging/debian debian
	dpkg-buildpackage -b -us -uc
	mv ../$(DEB_FILE) .

clean:
	rm -f icons/idle.png icons/processing.png icons/error.png
	rm -f *.deb
	rm -rf packaging/debian/$(PACKAGE) packaging/debian/.debhelper packaging/debian/tmp \
	       packaging/debian/debhelper-build-stamp packaging/debian/files

distclean: clean
	rm -rf venv
	rm -f debian

install:
	sudo apt-get install -y python3-venv python3-pip python3-dbus python3-gi ffmpeg
	sudo dpkg -i $(DEB_FILE)
