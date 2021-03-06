# NOTE this is named ``test_a_save...`` so that it is run first by py.test
# Since pytest doesn't import from scratch it stores the state of the pipeline
# and rolls it over causing problems due to combine latest.
# This will be fixed by having pipeline factories
import os
import time

from xpdan.pipelines.save_tiff import (raw_source,
                                       filler,
                                       fg_dark_query, save_kwargs)


def test_tiff_pipeline(exp_db, fast_tmp_dir, start_uid3):
    save_kwargs.update({'base_folder': fast_tmp_dir})
    # reset the DBs so we can use the actual db
    filler.db = exp_db
    for a in [fg_dark_query]:
        a.kwargs['db'] = exp_db

    t0 = time.time()
    for nd in exp_db[-1].documents(fill=True):
        name, doc = nd
        if name == 'start':
            nd = (name, doc)
        raw_source.emit(nd)
    t1 = time.time()
    print(t1 - t0)
    n_events = len(list(exp_db[-1].events()))
    for root, dirs, files in os.walk(fast_tmp_dir):
        level = root.replace(fast_tmp_dir, '').count(os.sep)
        indent = ' ' * 4 * level
        print('{}{}/'.format(indent, os.path.basename(root)))
        subindent = ' ' * 4 * (level + 1)
        for f in files:
            print('{}{}'.format(subindent, f))
    print(os.listdir(fast_tmp_dir))
    print(os.listdir(os.path.join(fast_tmp_dir, 'Au')))
    assert 'Au' in os.listdir(fast_tmp_dir)
    for f in ['dark_sub']:
        assert f in os.listdir(
            os.path.join(fast_tmp_dir, 'Au'))
        assert len(os.listdir(os.path.join(fast_tmp_dir, 'Au',
                                           f))) == n_events
    assert 'Au_{:.6}.yaml'.format(start_uid3) in os.listdir(
        os.path.join(fast_tmp_dir, 'Au', 'meta'))


def test_tiff_pipeline_no_background(exp_db, fast_tmp_dir, start_uid1):
    save_kwargs.update({'base_folder': fast_tmp_dir})
    # reset the DBs so we can use the actual db
    filler.db = exp_db
    for a in [fg_dark_query]:
        a.kwargs['db'] = exp_db

    t0 = time.time()
    for nd in exp_db[start_uid1].documents(fill=True):
        # Hack to change the output dir to the fast_tmp_dir
        name, doc = nd
        if name == 'start':
            nd = (name, doc)
        raw_source.emit(nd)
    t1 = time.time()
    print(t1 - t0)
    n_events = len(list(exp_db[start_uid1].events()))
    for root, dirs, files in os.walk(fast_tmp_dir):
        level = root.replace(fast_tmp_dir, '').count(os.sep)
        indent = ' ' * 4 * level
        print('{}{}/'.format(indent, os.path.basename(root)))
        subindent = ' ' * 4 * (level + 1)
        for f in files:
            print('{}{}'.format(subindent, f))
    print(os.listdir(fast_tmp_dir))
    print(os.listdir(os.path.join(fast_tmp_dir, 'kapton')))
    assert 'kapton' in os.listdir(fast_tmp_dir)
    for f in ['dark_sub']:
        assert f in os.listdir(
            os.path.join(fast_tmp_dir, 'kapton'))
        if f == 'mask':
            assert len(os.listdir(os.path.join(fast_tmp_dir, 'kapton', f))
                       ) == n_events * 2
        else:
            assert len(os.listdir(os.path.join(fast_tmp_dir, 'kapton', f))
                       ) == n_events
    assert 'kapton_{:.6}.yaml'.format(start_uid1) in os.listdir(
        os.path.join(fast_tmp_dir, 'kapton', 'meta'))
