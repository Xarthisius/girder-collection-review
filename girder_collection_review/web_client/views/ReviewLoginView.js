import template from '../templates/reviewLogin.pug';
import '../stylesheets/review.styl';

import * as session from '../session';

const View = girder.views.View;
const router = girder.router;
const { restRequest } = girder.rest;

/**
 * Chrome-free page that trades a review access key for a read-only session.
 */
const ReviewLoginView = View.extend({
    events: {
        'submit .g-review-login-form': function (e) {
            e.preventDefault();
            this._submit();
        }
    },

    initialize: function (settings) {
        this.message = (settings || {}).message || null;
        this.render();
    },

    render: function () {
        this.$el.html(template({
            message: this.message,
            warnExistingSession: session.hasNormalSession()
        }));

        this.$('.g-review-key').trigger('focus');

        return this;
    },

    _submit: function () {
        const key = (this.$('.g-review-key').val() || '').trim();
        if (!key) {
            return;
        }

        this.$('.g-review-error').text('');
        this.$('.g-review-submit').prop('disabled', true);

        restRequest({
            url: 'review/session',
            method: 'POST',
            data: { key: key },
            // Suppress core's 401/error handling; a failure here is expected user input
            // error, not a session expiry, and the login modal must not appear.
            error: null
        }).done((resp) => {
            session.adopt(resp.authToken.token);
            router.navigate('review/' + resp.collection._id, { trigger: true });
        }).fail((err) => {
            const message = (err.responseJSON && err.responseJSON.message) ||
                'Could not start the review session.';
            this.$('.g-review-error').text(message);
            this.$('.g-review-submit').prop('disabled', false);
        });
    }
});

export default ReviewLoginView;
