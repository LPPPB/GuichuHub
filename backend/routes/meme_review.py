"""All review endpoints require the existing administrator identity."""
import os
import time
from flask import jsonify, request
from services.meme_publication import get_meme_review_service, ReviewConflict, ReviewUnavailable


def register_meme_review_routes(app, require_admin, request_actor):
    @app.errorhandler(ReviewUnavailable)
    def unavailable(error):
        return jsonify(success=False, code='meme_publication_unavailable', message='梗库数据暂不可用，请稍后重试'), 503
    def endpoint(action):
        def route():
            denied = require_admin()
            if denied:
                return denied
            svc, now, owner = get_meme_review_service(), int(time.time()), request_actor()
            body = request.get_json(silent=True) or {}
            if not isinstance(body, dict):
                return jsonify(success=False, message='参数必须是对象'), 400
            try:
                if action == 'overview':
                    result = dict(svc.overview(owner, now), mode=os.environ.get('MEME_REVIEW_MODE', 'shadow'))
                elif action in ('dictionary', 'adjustments'):
                    result = svc.overview(owner, now)[action]
                elif action == 'evidence':
                    result = svc.evidence(request.args.get('board'), request.args.get('meme_id'), int(request.args.get('offset', 0)))
                elif action == 'draft':
                    result = svc.save_draft(owner, body['proposal'], body['revision'], now)
                elif action == 'preview':
                    result = svc.preview(body['proposal'], now)
                elif action == 'publish':
                    result = svc.publish(owner, body['request_id'], body['proposal'], body['token'], now)
                elif action == 'undo-preview':
                    result = svc.undo_preview(body['operation'], now, board=body.get('board'))
                elif action == 'undo':
                    result = svc.undo(owner, body['request_id'], body['operation'], body['token'], now, board=body.get('board'))
                else:
                    result = svc.cleanup_preview(now)
                response = jsonify(success=True, data=result)
                response.headers['Cache-Control'] = 'no-store'
                return response
            except ReviewConflict as error:
                return jsonify(success=False, conflict=True, message=str(error)), 409
            except (ValueError, KeyError, TypeError) as error:
                return jsonify(success=False, message=str(error)), 400
        return route

    for action, method in [('overview', 'GET'), ('dictionary', 'GET'), ('adjustments', 'GET'), ('evidence', 'GET'),
                           ('cleanup-preview', 'GET'), ('draft', 'PUT'), ('preview', 'POST'),
                           ('publish', 'POST'), ('undo-preview', 'POST'), ('undo', 'POST')]:
        app.add_url_rule('/api/admin/meme-review/'+action, 'meme-review-'+action, endpoint(action), methods=[method])
