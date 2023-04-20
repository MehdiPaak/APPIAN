FROM ace/appian:dev-base AS base
LABEL author="Mehdi Paak"

# for dev mount code volum to avoid rebuilding for eachg modification
FROM base AS dev
RUN rm -r /opt/APPIAN

# for prod pull latest from github
FROM base AS prod
RUN cd /opt/APPIAN && git pull --all 