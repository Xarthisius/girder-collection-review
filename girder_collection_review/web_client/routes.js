/* eslint-disable import/first */

const router = girder.router;
const events = girder.events;
const CollectionModel = girder.models.CollectionModel;
const Layout = girder.constants.Layout;

import * as session from './session';
import ReviewBrowseView from './views/ReviewBrowseView';
import ReviewLoginView from './views/ReviewLoginView';

router.route('review', 'reviewLogin', function () {
    events.trigger('g:navigateTo', ReviewLoginView, {}, { layout: Layout.EMPTY });
});

router.route('review/:collectionId', 'reviewBrowse', function (collectionId) {
    // Re-adopt the tab's token first so the fetches below are authenticated after a reload.
    if (!session.restore()) {
        router.navigate('review', { trigger: true, replace: true });
        return;
    }

    session.fetch().done((resp) => {
        if (!resp || !resp.review) {
            session.forget();
            events.trigger('g:navigateTo', ReviewLoginView, {
                message: 'This review has ended. Ask the journal editor for a new access key.'
            }, { layout: Layout.EMPTY });
            return;
        }

        // A real, fetched CollectionModel is required: HierarchyWidget reads
        // getAccessLevel() and resourceName off it.
        const collection = new CollectionModel({ _id: collectionId });
        collection.fetch({ ignoreError: true }).done(() => {
            session.loadReviewerUser().always(() => {
                events.trigger('g:navigateTo', ReviewBrowseView, {
                    collection: collection,
                    review: resp.review
                }, { layout: Layout.EMPTY });
            });
        }).fail(() => {
            session.forget();
            events.trigger('g:navigateTo', ReviewLoginView, {
                message: 'That access key does not grant access to this collection.'
            }, { layout: Layout.EMPTY });
        });
    }).fail(() => {
        session.forget();
        router.navigate('review', { trigger: true, replace: true });
    });
});
