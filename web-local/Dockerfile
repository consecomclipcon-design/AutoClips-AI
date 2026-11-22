FROM nginx:1.27-alpine
COPY web-local/index.html web-local/app.js web-local/saas.js web-local/render.worker.js web-local/review.html web-local/review.js web-local/studio.css web-local/studio-ui.js /usr/share/nginx/html/
COPY web-local/saas-config.template.json /tmp/saas-config.template.json
COPY web-local/nginx.conf.template /tmp/nginx.conf.template
COPY web-local/entrypoint.sh /opt/autoclips-entrypoint.sh
RUN chmod 755 /opt/autoclips-entrypoint.sh
EXPOSE 8080
ENTRYPOINT ["/opt/autoclips-entrypoint.sh"]
