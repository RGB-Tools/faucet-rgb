FROM python:3.12-slim-trixie

RUN apt-get -y update \
    && apt-get -y install --no-install-recommends adduser curl tini \
    && apt-get clean && rm -rf /var/lib/apt/lists/* /tmp/* /var/tmp/*

ENV PYTHONDONTWRITEBYTECODE="1" PYTHONIOENCODING="UTF-8" PYTHONUNBUFFERED="1"

# dir and user setup
ENV USER="faucet"
RUN adduser --disabled-password $USER
USER $USER
ENV APP_DIR="/home/$USER/faucet"
WORKDIR $APP_DIR

# project setup
ENV POETRY_VERSION=2.2.1
RUN python3 -m pip install --no-cache-dir poetry==${POETRY_VERSION} \
    && echo "export PATH=$PATH:$HOME/.local/bin" >> $HOME/.bashrc
COPY --chown=$USER:$USER poetry.lock pyproject.toml ./
COPY --chown=$USER:$USER faucet_rgb ./faucet_rgb

# install project
RUN $HOME/.local/bin/poetry install --without=dev

# copy remaining project code
COPY --chown=$USER:$USER . .

EXPOSE 8080/tcp
HEALTHCHECK CMD curl localhost:8080 || exit 1

CMD ["tini", "--", "/home/faucet/.local/bin/poetry", "run", "waitress-serve", "--host=0.0.0.0", "--call", "faucet_rgb:create_app"]
