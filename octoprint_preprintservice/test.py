from octoprint_preprintservice import PreprintservicePlugin, get_analysis_from_gcode
import unittest
import json
from unittest.mock import MagicMock, patch, PropertyMock, ANY
import tempfile
from requests import Response, ConnectionError as CE
from pathlib import Path
from octoprint.slicing import SlicingProfile
import logging

logging.basicConfig(level=logging.DEBUG)


class TestService(unittest.TestCase):

    def setUp(self):
        self.p = PreprintservicePlugin()
        self.p._settings = MagicMock()
        self.p._file_manager = MagicMock()
        self.p._slicing_manager = MagicMock()
        self.p._logger = logging.getLogger()
        td = tempfile.TemporaryDirectory()
        self.addCleanup(td.cleanup)
        self.d = Path(td.name)
        self.slice_args = [
                str(self.d / 'src.gcode'),
                'notused',
                str(self.d / 'dest.gcode'),
                str(self.d / 'profile'),
                ]
        with open(self.d / 'src.gcode', 'w') as f:
            f.write("testgcode")
        with open(self.d / 'profile', 'w') as f:
            f.write("testprofile")

    @patch('octoprint_preprintservice.flask')
    @patch('octoprint_preprintservice.Profile')
    def testImportSlic3rProfile(self, prof, mf):
        self.p._settings.global_get.side_effect = ["gcode", "gcode"] # upload name & path
        type(mf.request).values = PropertyMock(return_value={
            "file.gcode": "file.gcode",
        })
        prof.from_slic3r_ini.return_value = (dict(foo="bar"), "imported.ini", "description")

        self.p.importSlic3rProfile()
        self.p._slicing_manager.save_profile.assert_called_with(
                'preprintservice',
                'file',
                dict(foo="bar"),
                allow_overwrite=False,
                description='description',
                display_name='imported.ini'
        )
        mf.make_response.assert_called_with(ANY, 201)


    @patch('octoprint_preprintservice.flask')
    @patch('octoprint_preprintservice.Profile')
    def testImportSlic3rProfileAsFile(self, prof, mf):
        self.p._settings.global_get.side_effect = ["gcode", "gcode"] # upload name & path
        f = MagicMock(filename="foo.gcode")
        type(mf.request).files = PropertyMock(return_value={
            "file": f,
        })
        prof.from_slic3r_ini.return_value = (dict(foo="bar"), "imported.ini", "description")

        self.p.importSlic3rProfile()
        f.save.assert_called()
        self.p._slicing_manager.save_profile.assert_called_with(
                'preprintservice',
                'foo',
                dict(foo="bar"),
                allow_overwrite=False,
                description='description',
                display_name='imported.ini'
        )
        mf.make_response.assert_called_with(ANY, 201)

    @patch('octoprint_preprintservice.flask')
    @patch('octoprint_preprintservice.Profile')
    def testImportSlic3rProfileWithOverrides(self, prof, mf):
        self.p._settings.global_get.side_effect = ["gcode", "gcode"] # upload name & path
        f = MagicMock(filename="foo.gcode")
        type(mf.request).values = PropertyMock(return_value={
            "file.gcode": "file.gcode",
            "name": "nameOvr",
            "displayName": "displayNameOvr",
            "description": "descriptionOvr",
            "allowOverwrite": True,
        })
        prof.from_slic3r_ini.return_value = (dict(foo="bar"), "imported.ini", "description")
        self.p.importSlic3rProfile()
        self.p._slicing_manager.save_profile.assert_called_with(
                'preprintservice',
                'nameOvr',
                dict(foo="bar"),
                allow_overwrite=True,
                description='descriptionOvr',
                display_name='displayNameOvr',
        )

    @patch('octoprint_preprintservice.flask')
    def testImportSlic3rProfileBadRequest(self, mf):
        type(mf.request).values = PropertyMock(return_value={})
        self.p.importSlic3rProfile()
        mf.make_response.assert_called_with(ANY, 400)

    @patch('octoprint_preprintservice.requests')
    def testIsSlicerConfiguredOk(self, preq):
        preq.get.return_value = MagicMock(status_code=200)
        self.assertTrue(self.p.is_slicer_configured())

    @patch('octoprint_preprintservice.requests', ConnectionError=CE)
    def testIsSlicerConfiguredNoConnection(self, preq):
        preq.get.side_effect = CE()
        self.assertFalse(self.p.is_slicer_configured())

    @patch('octoprint_preprintservice.Profile')
    def testGetSlicerDefaultProfile(self, prof):
        # Also implicitly tests get_slicer_profile
        self.p._settings.get.return_value = "testpath"
        prof.from_slic3r_ini.return_value = (dict(foo="bar"), "imported.ini", "description")
        ret = self.p.get_slicer_default_profile()
        self.assertEqual(ret.slicer, 'preprintservice')
        self.assertEqual(ret.name, 'unknown')
        self.assertEqual(ret.display_name, 'imported.ini')
        self.assertEqual(ret.description, 'description')
        self.assertEqual(ret.default, False)

    def testSaveSlicerProfile(self):
        with tempfile.NamedTemporaryFile() as f:
            self.p.save_slicer_profile(f.name, SlicingProfile(
                "foo",
                "display",
                display_name="foo",
                description="description",
                data=dict(),
            ))
            with open(f.name, 'r') as f2:
                self.assertEqual(f2.read(), "# Name: foo\n# Description: description\n")

    @patch('octoprint_preprintservice.requests')
    def testIsSlicerConfiguredBadResponse(self, preq):
        preq.get.return_value = MagicMock(status_code=500)
        self.assertFalse(self.p.is_slicer_configured())

    @patch('octoprint_preprintservice.requests')
    def testSliceSuccessful(self, preq):
        preq.post.return_value = MagicMock(status_code=200, content=b"testresponse")
        ok, analysis = self.p.do_slice(*self.slice_args)
        self.assertEqual(ok, True)
        with open(self.d / 'dest.gcode', 'r') as f:
            self.assertEqual(f.read(), "testresponse")

    @patch('octoprint_preprintservice.requests')
    def testSliceFailedBadResponse(self, preq):
        preq.post.return_value = MagicMock(status_code=500)
        ok, analysis = self.p.do_slice(*self.slice_args)
        self.assertEqual(ok, False)

    @patch('octoprint_preprintservice.requests')
    def testSliceFailedException(self, preq):
        preq.post.return_value.side_effect = Exception("womp womp")
        ok, analysis = self.p.do_slice(*self.slice_args)
        self.assertEqual(ok, False)

    @patch('octoprint_preprintservice.requests')
    def testSliceOnlyTweak(self, preq):
        self.p._settings.get.side_effect = ["tweak", "tweak", "url"]
        self.p._settings.get_boolean.return_value = False
        preq.post.return_value = MagicMock(status_code=200, content=b"")
        self.p.do_slice(*self.slice_args)
        self.assertEqual(preq.post.call_args[1]['data']['tweak_actions'], 'tweak')

    @patch('octoprint_preprintservice.requests')
    def testSliceOnlySlice(self, preq):
        self.p._settings.get.side_effect = ["slice", "slice", "url"]
        self.p._settings.get_boolean.return_value = False
        preq.post.return_value = MagicMock(status_code=200, content=b"")
        self.p.do_slice(*self.slice_args)
        self.assertEqual(preq.post.call_args[1]['data']['tweak_actions'], 'slice')

class TestAnalysis(unittest.TestCase):
    def testNoFile(self):
        self.assertEquals(get_analysis_from_gcode('bogus_path.gcode'), {'estimatedPrintTime': -1, 'filament': {'tool0': {'length': -1, 'volume': -1}}})

    def testEmptyFile(self):
        with tempfile.NamedTemporaryFile() as f:
            self.assertEquals(get_analysis_from_gcode(f.name), {'estimatedPrintTime': -1, 'filament': {'tool0': {'length': -1, 'volume': -1}}})

    def testParseSuccessful(self):
        with tempfile.NamedTemporaryFile() as f:
            with open(f.name, 'w') as h:
                h.write('; filament used = 5mm (3cm3)\n')
                h.write('; estimated printing time = 1d3h')
            self.assertEquals(get_analysis_from_gcode(f.name), {
                'estimatedPrintTime': 86400.0,
                'filament': {'tool0': {'length': 5, 'volume': 3}}})
