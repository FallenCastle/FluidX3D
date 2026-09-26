# SPHERIC Test 2 reference data

`spheric-test2-levels.csv` contains H1–H4 water-level measurements from 0 to 3 s at 0.01 s intervals. Values are linearly interpolated from `test_case_2_exp_data.xls` in the official SPHERIC Test 2 archive.

- Benchmark page: https://www.spheric-sph.org/tests/test-02
- Test description: `test_case_2_v1p1.pdf`, release 1.1, March 2006, R. Issa and D. Violeau
- Downloaded archive SHA256: `a2ad06e367f61c70351f3d66a8dc5041b53972e3a3aecebde0e06efdd62bf6d1`
- Source XLS SHA256: `8126f8c8f6effb9e8bfb245a2d098186e9ebee2ef6e75fcb1b3166af17883d8c`
- Derived CSV SHA256: `f08ec7bf57f3f1185a45b01d70a3365357975871e8c1950bc7708a63dcc34f83`
- Derived CSV method: linear interpolation at exact 0.01 s timestamps; no filtering, smoothing, phase shift or amplitude scaling

The solver benchmark uses the published 3.22 m × 1.00 m × 1.00 m tank, 1.228 m × 0.55 m initial water column, 0.403 m × 0.161 m × 0.161 m obstacle, and the published H1–H4 locations. Coordinates follow the official `test_case_2.f` geometry (the horizontal direction is the mirror image of the schematic's plotted x-axis). The V2 acceptance window is fixed to 0–3 s before running the solver. Acceptance requires normalized four-probe RMSE no greater than 20% of the 0.55 m initial depth and first-arrival errors no greater than 0.15 s at H1–H3, where arrival is the first level above 0.02 m.
