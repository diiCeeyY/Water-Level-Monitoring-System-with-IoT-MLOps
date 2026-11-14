FROM nodered/node-red:4.0.9-22

USER root
RUN cd /usr/src/node-red && npm install --omit=dev node-red-contrib-postgresql@0.16.2
USER node-red
