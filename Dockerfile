# syntax=docker/dockerfile:1.3-labs

ARG BASE_IMAGE=ubuntu:focal
ARG BASE_RUNTIME_IMAGE=$BASE_IMAGE

# Download VOICEVOX Core shared object
FROM ${BASE_IMAGE} AS download-core-env
ARG DEBIAN_FRONTEND=noninteractive

WORKDIR /work

RUN <<EOF
    set -eux

    apt-get update
    apt-get install -y \
        wget \
        unzip
    apt-get clean
    rm -rf /var/lib/apt/lists/*
EOF


# Compile Python (version locked)
FROM ${BASE_IMAGE} AS compile-python-env

ARG DEBIAN_FRONTEND=noninteractive

RUN <<EOF
    set -eux
    apt-get update
    apt-get install -y \
        build-essential \
        libssl-dev \
        zlib1g-dev \
        libbz2-dev \
        libreadline-dev \
        libsqlite3-dev \
        wget \
        curl \
        llvm \
        libncurses5-dev \
        libncursesw5-dev \
        xz-utils \
        tk-dev \
        libffi-dev \
        liblzma-dev \
        python-openssl \
        git
    apt-get clean
    rm -rf /var/lib/apt/lists/*
EOF

ARG PYTHON_VERSION=3.8.10
# FIXME: Lock pyenv version with git tag
# 90d0d20508a91e7ea1e609e8aa9f9d1a28bb563e (including 3.7.12) not released yet (2021-09-12)
ARG PYENV_VERSION=master
ARG PYENV_ROOT=/tmp/.pyenv
ARG PYBUILD_ROOT=/tmp/python-build
RUN <<EOF
    set -eux

    git clone -b "${PYENV_VERSION}" https://github.com/pyenv/pyenv.git "$PYENV_ROOT"
    PREFIX="$PYBUILD_ROOT" "$PYENV_ROOT"/plugins/python-build/install.sh
    "$PYBUILD_ROOT/bin/python-build" -v "$PYTHON_VERSION" /opt/python

    rm -rf "$PYBUILD_ROOT" "$PYENV_ROOT"
EOF

# FIXME: add /opt/python to PATH
# not working: /etc/profile read only on login shell
# not working: /etc/environment is the same
# not suitable: `ENV` is ignored by docker-compose
# RUN <<EOF
#     set -eux
#     echo "export PATH=/opt/python/bin:\$PATH" > /etc/profile.d/python-path.sh
#     echo "export LD_LIBRARY_PATH=/opt/python/lib:\$LD_LIBRARY_PATH" >> /etc/profile.d/python-path.sh
#     echo "export C_INCLUDE_PATH=/opt/python/include:\$C_INCLUDE_PATH" >> /etc/profile.d/python-path.sh
#
#     rm -f /etc/ld.so.cache
#     ldconfig
# EOF


# Runtime
FROM ${BASE_RUNTIME_IMAGE} AS runtime-env
ARG DEBIAN_FRONTEND=noninteractive

WORKDIR /opt/voicevox_engine

# libsndfile1: soundfile shared object
# ca-certificates: pyopenjtalk dictionary download
# build-essential: pyopenjtalk local build
RUN <<EOF
    set -eux

    apt-get update
    apt-get install -y \
        git \
        cmake \
        libsndfile1 \
        ca-certificates \
        build-essential \
        gosu
    apt-get clean
    rm -rf /var/lib/apt/lists/*

    # Create a general user
    useradd --create-home user
EOF

# Copy python env
COPY --from=compile-python-env /opt/python /opt/python

# Install Python dependencies
ADD ./requirements.txt /tmp/
RUN <<EOF
    # Install requirements
    # FIXME: Nuitka cannot build with setuptools>=60.7.0
    # https://github.com/Nuitka/Nuitka/issues/1406
    gosu user /opt/python/bin/python3 -m pip install --upgrade pip setuptools==60.6.0 wheel
    gosu user /opt/python/bin/pip3 install -r /tmp/requirements.txt
EOF

# Add local files
ADD ./voicevox_engine /opt/voicevox_engine/voicevox_engine
ADD ./docs /opt/voicevox_engine/docs
ADD ./run.py ./generate_licenses.py ./presets.yaml ./user.dic /opt/voicevox_engine/
ADD ./speaker_info /opt/voicevox_engine/speaker_info
ADD ./espnet /opt/voicevox_engine/espnet

# Replace version
ARG VOICEVOX_ENGINE_VERSION=latest
RUN sed -i "s/__version__ = \"latest\"/__version__ = \"${VOICEVOX_ENGINE_VERSION}\"/" /opt/voicevox_engine/voicevox_engine/__init__.py

# Generate licenses.json
RUN <<EOF
    set -eux

    cd /opt/voicevox_engine

    # Define temporary env vars
    # /home/user/.local/bin is required to use the commands installed by pip
    export PATH="/home/user/.local/bin:${PATH:-}"

    gosu user /opt/python/bin/pip3 install pip-licenses
    gosu user /opt/python/bin/python3 generate_licenses.py > /opt/voicevox_engine/licenses.json
EOF

# Keep this layer separated to use layer cache on download failed in local build
RUN <<EOF
    set -eux

    # Download openjtalk dictionary
    # try 5 times, sleep 5 seconds before retry
    for i in $(seq 5); do
        EXIT_CODE=0
        gosu user /opt/python/bin/python3 -c "import pyopenjtalk; pyopenjtalk._lazy_init()" || EXIT_CODE=$?
        if [ "$EXIT_CODE" = "0" ]; then
            break
        fi
        sleep 5
    done

    if [ "$EXIT_CODE" != "0" ]; then
        exit "$EXIT_CODE"
    fi
EOF

# Create container start shell
COPY --chmod=775 <<EOF /entrypoint.sh
#!/bin/bash
set -eux

exec "\$@"
EOF

ENTRYPOINT [ "/entrypoint.sh"  ]
CMD [ "gosu", "user", "/opt/python/bin/python3", "./run.py", "--host", "0.0.0.0" ]

# Enable use_gpu
FROM runtime-env AS runtime-nvidia-env
CMD [ "gosu", "user", "/opt/python/bin/python3", "./run.py", "--use_gpu", "--host", "0.0.0.0" ]

# Binary build environment (common to CPU, GPU)
FROM runtime-env AS build-env

# Install ccache for Nuitka cache
# chrpath: required for nuitka build; 'RPATH' settings in used shared
RUN <<EOF
    set -eux

    apt-get update
    apt-get install -y \
        ccache \
        chrpath \
        patchelf
    apt-get clean
    rm -rf /var/lib/apt/lists/*
EOF

# Install Python build dependencies
ADD ./requirements-dev.txt /tmp/
RUN <<EOF
    set -eux

    gosu user /opt/python/bin/pip3 install -r /tmp/requirements-dev.txt
EOF

# Generate licenses.json with build dependencies
RUN <<EOF
    set -eux

    cd /opt/voicevox_engine

    # Define temporary env vars
    # /home/user/.local/bin is required to use the commands installed by pip
    export PATH="/home/user/.local/bin:${PATH:-}"

    gosu user /opt/python/bin/pip3 install pip-licenses
    gosu user /opt/python/bin/python3 generate_licenses.py > /opt/voicevox_engine/licenses.json
EOF

# Create build script
RUN <<EOF
    set -eux

    cat <<EOD > /build.sh
        #!/bin/bash
        set -eux

        # chown general user c.z. mounted directory may be owned by root
        mkdir -p /opt/voicevox_engine_build
        chown -R user:user /opt/voicevox_engine_build

        mkdir -p /home/user/.cache/Nuitka
        chown -R user:user /home/user/.cache/Nuitka

        cd /opt/voicevox_engine_build

        gosu user /opt/python/bin/python3 -m nuitka \
            --output-dir=/opt/voicevox_engine_build \
            --standalone \
            --plugin-enable=numpy \
            --plugin-enable=torch \
            --follow-import-to=numpy \
            --follow-import-to=aiofiles \
            --include-package=uvicorn \
            --include-package=anyio \
            --include-package-data=pyopenjtalk \
            --include-package-data=scipy \
            --include-data-file=/opt/voicevox_engine/licenses.json=./ \
            --include-data-file=/opt/voicevox_engine/presets.yaml=./ \
            --include-data-file=/opt/voicevox_engine/user.dic=./ \
            --include-data-dir=/opt/voicevox_engine/speaker_info=./speaker_info \
            --include-data-dir=/opt/voicevox_engine/espnet=./espnet \
            --follow-imports \
            --no-prefer-source-code \
            /opt/voicevox_engine/run.py

        chmod +x /opt/voicevox_engine_build/run.dist/run
EOD
    chmod +x /build.sh
EOF

CMD [ "bash", "/build.sh" ]
