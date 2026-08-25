import template from '../templates/reviewBrowse.pug';
import '../stylesheets/review.styl';

import * as session from '../session';
import ReviewItemView from './ReviewItemView';

const View = girder.views.View;
const HierarchyWidget = girder.views.widgets.HierarchyWidget;
const router = girder.router;

/** How often to notice that the owner closed the review out from under us. */
const POLL_INTERVAL_MS = 60 * 1000;

/**
 * Chrome-free read-only browser for a collection under review.
 */
const ReviewBrowseView = View.extend({
    events: {
        'click .g-review-exit': function (e) {
            e.preventDefault();
            session.end().always(() => {
                router.navigate('', { trigger: true });
            });
        },

        'click .g-review-back-to-hierarchy': function (e) {
            e.preventDefault();
            this._showHierarchy();
        }
    },

    initialize: function (settings) {
        this.collection = settings.collection;
        this.review = settings.review;
        this.ended = false;

        this.render();
        this._startPolling();
    },

    render: function () {
        this.$el.html(template({
            collection: this.collection,
            review: this.review,
            ended: this.ended
        }));

        if (!this.ended) {
            this._showHierarchy();
        }

        return this;
    },

    _showHierarchy: function () {
        if (this.itemView) {
            this.itemView.destroy();
            this.itemView = null;
        }

        this.$('.g-review-item-container').empty().addClass('hide');
        this.$('.g-review-hierarchy').removeClass('hide');

        if (this.hierarchyWidget) {
            return;
        }

        this.hierarchyWidget = new HierarchyWidget({
            el: this.$('.g-review-hierarchy'),
            parentModel: this.collection,
            parentView: this,
            // Left on: every mutating control inside the actions header is separately gated
            // on WRITE/ADMIN, so at READ the menu collapses to "Download collection", which
            // is exactly what a reviewer wants. Turning it off would lose the download.
            showActions: true,
            // Off: the bulk "checked actions" menu is not access-gated as a whole.
            checkboxes: false,
            // Off: the widget otherwise rewrites the hash to the core collection/folder
            // routes, which on reload would render with the full navigation chrome.
            routing: false,
            downloadLinks: true,
            onItemClick: (item) => this._showItem(item)
        });
    },

    _showItem: function (item) {
        this.$('.g-review-hierarchy').addClass('hide');
        this.$('.g-review-item-container').removeClass('hide');

        if (this.itemView) {
            this.itemView.destroy();
        }

        this.itemView = new ReviewItemView({
            el: this.$('.g-review-item-container'),
            parentView: this,
            item: item
        });
    },

    _startPolling: function () {
        this._poll = window.setInterval(() => {
            session.fetch().done((resp) => {
                if (!resp || !resp.review) {
                    this._onReviewEnded();
                }
            });
        }, POLL_INTERVAL_MS);
    },

    _onReviewEnded: function () {
        if (this.ended) {
            return;
        }

        this.ended = true;
        this._stopPolling();

        if (this.hierarchyWidget) {
            this.hierarchyWidget.destroy();
            this.hierarchyWidget = null;
        }
        if (this.itemView) {
            this.itemView.destroy();
            this.itemView = null;
        }

        session.forget();
        this.render();
    },

    _stopPolling: function () {
        if (this._poll) {
            window.clearInterval(this._poll);
            this._poll = null;
        }
    },

    destroy: function () {
        this._stopPolling();
        View.prototype.destroy.apply(this, arguments);
    }
});

export default ReviewBrowseView;
