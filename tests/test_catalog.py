import unittest
from decimal import Decimal
from explabs.catalog import normalize, select_models, catalog


def row(id, price='0.000001', slug=None):
    return {'id':id, 'canonical_slug':slug or id.split('/')[-1],
            'name':id, 'pricing':{'prompt':price,'completion':'0.000004'},
            'context_length':100000, 'architecture':{'output_modalities':['text']},
            'supported_parameters':['tools']}


class CatalogTests(unittest.TestCase):
    def test_units_missing_price_and_free_variants(self):
        models = normalize([row('a/model'), row('a/model:free','0','model'),row('b/m',None)], {})
        self.assertEqual(models[0]['input_usd_per_million'], Decimal('1'))
        self.assertEqual(models[0]['reference_usd'], Decimal('2'))
        self.assertIsNone(models[2]['reference_usd'])
        self.assertNotEqual(models[0]['id'],models[1]['id'])
        self.assertTrue(models[1]['variant'])

    def test_shortlist_diversity_and_specialized_exclusion(self):
        rows=[row('a/m1'),row('a/m2'),row('a/m3'),row('b/m4'),row('b/m4:free','0','m4'),row('b/m5-uncensored')]
        metadata={r['canonical_slug']:{'preferred_rank':i} for i,r in enumerate(rows)}
        selected=select_models(normalize(rows,metadata))
        self.assertEqual({m['id'] for m in selected},{'a/m1','a/m2','b/m4'})

    def test_full_search_and_unknown_prices_last(self):
        models=normalize([row('a/unknown',None),row('a/expensive','0.00001'),row('b/cheap','0.0000001')],{})
        self.assertEqual([m['id'] for m in select_models(models,all_models=True,sort='price')],['b/cheap','a/expensive','a/unknown'])
        self.assertEqual(len(select_models(models,search='EXPENSIVE')),1)
        self.assertEqual(len(select_models(models,all_models=True,max_cost=Decimal('2'))),1)

    def test_invalid_money_is_not_free(self):
        for price in ('NaN','-1','oops'):
            with self.assertRaises(ValueError):normalize([row('a/m',price)],{})

    def test_shortlist_metadata_failure_is_explicit(self):
        from explabs.client import APIError
        class Client:
            def get(self,path,params=None):
                if path=='/api/v1/models': return {'data':[row('a/m')]}
                raise APIError(path,503)
        result=catalog(Client())
        self.assertTrue(result['warnings'])
        self.assertEqual(result['models'],[])


class CatalogCLITests(unittest.TestCase):
    def test_models_command_and_json_filters(self):
        import io, json
        from contextlib import redirect_stdout
        from unittest.mock import patch
        from explabs.cli import main
        class Client:
            def get(self,path,params=None):
                if path == '/api/v1/models':return {'data':[row('a/cheap','0.0000001'),row('b/expensive','0.00001')]}
                return {'models':[]}
        stream=io.StringIO()
        with patch('explabs.cli.load_key',return_value='secret'), patch('explabs.cli.Client',return_value=Client()), redirect_stdout(stream):
            self.assertEqual(main(['models','--env-file','.env','--all','--sort','price','--max-cost','2','--json']),0)
        data=json.loads(stream.getvalue())
        self.assertEqual(data['shown'],1)
        self.assertEqual(data['models'][0]['input_usd_per_million'],'0.1000000')

    def test_maker_spelling_does_not_bypass_diversity(self):
        rows=[row('z-ai/m1'),row('z-ai/m2'),row('z-ai/m3')]
        metadata={f'm{i}':{'preferred_rank':i, 'maker':'Z.ai' if i==1 else None} for i in range(1,4)}
        self.assertEqual(len(select_models(normalize(rows,metadata))),2)

    def test_nontext_has_no_reference_workload(self):
        r=row('a/image');r['architecture']['output_modalities']=['image']
        self.assertIsNone(normalize([r],{})[0]['reference_usd'])
