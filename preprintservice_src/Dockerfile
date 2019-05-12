FROM python:3.6
MAINTAINER Christoph Schranz <christoph.schranz@salzburgresearch.at>

# Copy the content of this folder into the hosts home directory and install the requirements first.
ADD requirements.txt .
RUN pip install -r requirements.txt
RUN mkdir /tmp || true


# Install Slic3r
RUN apt-get update && apt-get install -y \
  freeglut3 \
  libgtk2.0-dev \
  libwxgtk3.0-dev \
  libwx-perl \
  libxmu-dev \
  libgl1-mesa-glx \
  libgl1-mesa-dri \
  xdg-utils \
  jq \
  curl \
  ca-certificates \
  unzip \
  bzip2 \
  git \
  --no-install-recommends \
  && rm -rf /var/lib/apt/lists/* \
  && apt-get autoremove -y \
  && apt-get autoclean

RUN groupadd slic3r \
  && useradd -g slic3r --create-home --home-dir /home/slic3r slic3r \
  && mkdir -p /Slic3r \
  && chown slic3r:slic3r /Slic3r

ARG SLIC3R_VERSION
RUN apt-get update && apt-get install -y \
  --no-install-recommends \
  && mkdir -p /Slic3r/slic3r-dist \
  && curl -sSL ${SLIC3R_VERSION} > /Slic3r/slic3r.tar.bz2 \
  && tar -xjf /Slic3r/slic3r.tar.bz2 -C /Slic3r/slic3r-dist --strip-components 1 \
  && rm -f /Slic3r/slic3r.tar.bz2 \
  && rm -rf /var/lib/apt/lists/* \
  && apt-get purge -y --auto-remove jq unzip bzip2 \
  && apt-get autoclean \
  && chown -R slic3r:slic3r /Slic3r /home/slic3r

# Settings storage
RUN mkdir -p /home/slic3r/.local/share/

ADD . /src/.

# Clone if Tweaker-3 doesn't exist, and pull.
RUN ls /src/Tweaker-3/README.md  > /dev/null 2>&1  \
  || (echo "Tweaker not found, cloning repository" \
    && git clone https://github.com/ChristophSchranz/Tweaker-3 /src/Tweaker-3) \
  && cd /src/Tweaker-3 \
  && git pull

# setup proper configuration
ENV PYTHONPATH /src/.
ENV WORKDIR /src/

ENTRYPOINT ["python3", "/src/tweak-service.py"]
