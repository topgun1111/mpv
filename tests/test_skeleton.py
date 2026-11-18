"""Çöp adam (iskelet) mesajı: Python → Lua dizesi (model gerekmez)."""
import numpy as np

from tracker.geometry import BBox
from tracker.live import skeleton_message
from tracker.pose import Pose


def _pose(first=(100.0, 50.0, 0.9)):
    k = np.zeros((17, 3), dtype=np.float32)
    k[0] = first
    return Pose(bbox=BBox(0, 0, 10, 10), score=0.9, kpts=k)


def test_empty_is_dash():
    assert skeleton_message([], 200, 200) == "-"


def test_one_person_has_17_normalized_points():
    msg = skeleton_message([_pose()], 200, 100)
    pts = msg.split(";")
    assert len(pts) == 17 and "|" not in msg
    assert pts[0] == "0.5000,0.5000,0.90"


def test_two_people_are_separated():
    msg = skeleton_message([_pose(), _pose()], 200, 200)
    assert len(msg.split("|")) == 2
