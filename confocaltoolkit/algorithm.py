"""Analysis primitives re-exported from the research prototype.

Art.Suleimanov1924
"""

from analyze_confocal import (
    FIELD_SIZE_UM,
    FULL_AREA_MM2,
    IMAGE_SIZE_PX,
    PIXEL_SIZE_UM,
    analyze_frame,
    format_stat,
    frangi_like,
    make_overlay,
    otsu_threshold,
    remove_small_objects,
    rescale01,
    save_contact_sheet,
    summarize,
)

METRIC_COLUMNS = [
    "cnfd_fibers_per_mm2_proxy",
    "cnfl_mm_per_mm2",
    "cnbd_branches_per_mm2_proxy",
    "ctbd_branches_per_mm2_proxy",
    "cnfa_mm2_per_mm2",
    "cnfw_mean_um_proxy",
    "cnfracdim_proxy",
    "tortuosity_ratio_proxy",
]
