"""Browser integration checks against a running local backend and real saved runs."""
import argparse
import json
from pathlib import Path
from playwright.sync_api import sync_playwright, expect


def main():
    p=argparse.ArgumentParser();p.add_argument('--url',default='http://127.0.0.1:8765')
    p.add_argument('--token-file',default='.cache/api.token')
    p.add_argument('--results',default='output/real-run');p.add_argument('--output',default='output/browser')
    args=p.parse_args();root=Path(args.results);out=Path(args.output);out.mkdir(parents=True,exist_ok=True)
    errors=[]
    with sync_playwright() as pw:
        browser=pw.chromium.launch(headless=True,args=['--use-angle=swiftshader','--enable-unsafe-swiftshader'])
        page=browser.new_page(viewport={'width':1440,'height':1000},device_scale_factor=1)
        page.on('pageerror',lambda error:errors.append(str(error)))
        page.goto(args.url, wait_until="load")
        assert page.locator('h1').inner_text().startswith('See the range.')
        page.locator('#saved').set_input_files(str(root/'forecast.json'))
        page.locator("#fan .main-svg").first.wait_for(state="visible")
        assert '8 sample paths' in page.locator('#sample-count').inner_text()
        page.locator('#density-toggle').check()
        page.locator("#density canvas").first.wait_for(state="visible")
        page.screenshot(path=str(out/'forecast-desktop.png'),full_page=True)
        with page.expect_download() as download:
            page.locator('#export').click()
        assert 'trajectories' in json.loads(Path(download.value.path()).read_text())
        page.locator('#saved').set_input_files(str(root/'evaluation.json'))
        expect(page.locator("#metrics tr")).to_have_count(6)
        assert page.locator('#window option').count()==8
        page.screenshot(path=str(out/'evaluation-desktop.png'),full_page=True)
        irregular=json.loads((root/'evaluation.json').read_text())
        irregular['final_forecast']=None
        irregular['final_forecast_error']='Explicit future exchange sessions required'
        saved=out/'irregular-evaluation.json';saved.write_text(json.dumps(irregular))
        page.locator('#saved').set_input_files(str(saved))
        expect(page.locator('#expected')).to_have_text('—')
        expect(page.locator('#fan .main-svg')).to_have_count(0)
        expect(page.locator('#density')).to_be_hidden()
        expect(page.locator('#metadata')).to_contain_text('Explicit future exchange sessions required')
        page.locator('#saved').set_input_files(str(root/'comparison.json'))
        expect(page.locator("#comparison-panel")).to_be_visible()
        assert 'Chronos-2' in page.locator('#comparison-note').inner_text()
        # End-to-end authenticated request through the actual browser and model service.
        page.locator('#token').fill(Path(args.token_file).read_text().strip())
        page.locator('#lookback').fill('64');page.locator('#horizon').fill('8');page.locator('#samples').fill('8')
        page.locator('#forecast').click()
        expect(page.locator("#status")).to_contain_text("forecast completed", timeout=120000)
        assert not page.locator('#status').get_attribute('class')
        page.set_viewport_size({'width':390,'height':844})
        page.wait_for_timeout(500)
        assert page.evaluate('document.documentElement.scrollWidth <= window.innerWidth')
        page.screenshot(path=str(out/'forecast-mobile.png'),full_page=True)
        browser.close()
    if errors:raise AssertionError(errors)
    (out/'result.json').write_text(json.dumps({'passed':True,'checks':['forecast rendering','3D density','JSON export','held-out evaluation','Chronos2 comparison','authenticated real forecast job','mobile layout','clears stale forecasts for irregular sessions'],'javascript_errors':errors},indent=2)+'\n')
    print('Browser smoke passed: forecast, evaluation, comparison, 3D, export, real API job, mobile')


if __name__=='__main__':main()
