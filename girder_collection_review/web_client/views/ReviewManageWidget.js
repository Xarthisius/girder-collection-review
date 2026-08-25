import template from '../templates/reviewManageWidget.pug';
import '../stylesheets/review.styl';

const $ = girder.$;
const View = girder.views.View;
const events = girder.events;
const { confirm } = girder.dialog;
const { restRequest } = girder.rest;
const { formatDate, DATE_SECOND } = girder.misc;

/**
 * Owner-facing modal: open a review round, read the access key once, and close rounds.
 */
const ReviewManageWidget = View.extend({
    events: {
        'click .g-review-open': function () {
            this._open();
        },

        'click .g-review-close': function (e) {
            const reviewId = $(e.currentTarget).attr('review-id');
            confirm({
                text: 'End this review? The access key stops working immediately and any ' +
                      'reviewer currently browsing will lose access.',
                yesText: 'End review',
                confirmCallback: () => this._close(reviewId)
            });
        },

        'click .g-review-copy-key': function () {
            this.$('.g-review-key-value').trigger('select');
            try {
                document.execCommand('copy');
            } catch (e) {
                // Clipboard access is best-effort; the field is selected either way.
            }
        }
    },

    initialize: function (settings) {
        this.collection = settings.collection;
        this.reviews = [];
        this.newKey = null;
        this.busy = false;

        this._fetch();
    },

    render: function () {
        const modal = this.$el.html(template({
            collection: this.collection,
            reviews: this.reviews,
            newKey: this.newKey,
            busy: this.busy,
            formatDate: formatDate,
            DATE_SECOND: DATE_SECOND
        })).girderModal(this);

        modal.trigger($.Event('ready.girder.modal', { relatedTarget: modal }));

        if (this.newKey) {
            this.$('.g-review-key-value').trigger('select');
        }

        return this;
    },

    _fetch: function () {
        restRequest({
            url: 'review',
            data: { collectionId: this.collection.id }
        }).done((resp) => {
            this.reviews = resp;
            this.render();
        });
    },

    _open: function () {
        if (this.busy) {
            return;
        }

        const duration = this.$('.g-review-duration').val();
        this.busy = true;
        this.$('.g-review-open').prop('disabled', true);

        restRequest({
            url: 'review',
            method: 'POST',
            data: {
                collectionId: this.collection.id,
                duration: duration || undefined
            }
        }).done((resp) => {
            this.busy = false;
            // The key is returned exactly once, so it has to be surfaced now.
            this.newKey = resp.key;
            this._fetch();
        }).fail((err) => {
            this.busy = false;
            events.trigger('g:alert', {
                text: (err.responseJSON && err.responseJSON.message) ||
                    'Could not open the review.',
                type: 'danger',
                timeout: 5000
            });
            this.render();
        });
    },

    _close: function (reviewId) {
        restRequest({
            url: 'review/' + reviewId,
            method: 'DELETE'
        }).done(() => {
            this.newKey = null;
            this._fetch();
        });
    }
});

export default ReviewManageWidget;
