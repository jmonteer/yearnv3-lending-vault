from ape import project, accounts, Contract, chain
from ape.utils import ZERO_ADDRESS
from web3 import Web3, HTTPProvider
from hexbytes import HexBytes
import os
from enum import IntFlag

ASSET_ADDRESS = "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48"  # USDC
AASSET_ADDRESS = "0xBcca60bB61934080951369a648Fb03DF4F96263C"  # AUSDC
ASSET_WHALE_ADDRESS = "0x0A59649758aa4d66E25f08Dd01271e891fe52199"  # USDC WHALE
CASSET_ADDRESS = "0x39AA39c021dfbaE8faC545936693aC917d5E7563"  # cUSDC
CASSETV3_ADDRESS = "0xc3d688B66703497DAA19211EEdff47f25384cdc3"  # cUSDCv3
COMP_ADDRESS = "0xc00e94Cb662C3520282E6f5717214004A7f26888"  # COMP
COMP_WHALE_ADDRESS = "0x5608169973d639649196a84ee4085a708bcbf397"  # COMP whale

class ROLES(IntFlag):
    STRATEGY_MANAGER = 1
    DEBT_MANAGER = 2
    EMERGENCY_MANAGER = 4
    ACCOUNTING_MANAGER = 8


if True:
    print("ChainID", chain.chain_id)
    publish_flag = False
    if chain.chain_id == 1:
        publish_flag = True
    # if input("Do you want to continue?") == "n":
        # return
    
    # we default to local node
    w3 = Web3(HTTPProvider(os.getenv("CHAIN_PROVIDER", "http://127.0.0.1:8545")))
    
    vault_factory = project.dependencies["yearn-vaults-v3"]["master"].VaultFactory
    vault = project.dependencies["yearn-vaults-v3"]["master"].VaultV3
    debtmanager = project.dependencies["debt-manager"]["master"].LenderDebtManager
    strategy_comp_v3 = project.dependencies["strategy-comp-v3"]["master"].Strategy
    strategy_aave_v2 = project.dependencies["strategy-aave-v2"]["master"].Strategy
    strategy_comp_v2 = project.dependencies["strategy-comp-v2"]["master"].Strategy
    
    deployer = accounts.load("v3_deployer")
    
    from copy import deepcopy

    vault_copy = deepcopy(vault)

    # generate and deploy blueprint 
    blueprint_bytecode = b"\xFE\x71\x00" + HexBytes(
        vault_copy.contract_type.deployment_bytecode.bytecode
    )  # ERC5202
    len_bytes = len(blueprint_bytecode).to_bytes(2, "big")
    deploy_bytecode = HexBytes(
        b"\x61" + len_bytes + b"\x3d\x81\x60\x0a\x3d\x39\xf3" + blueprint_bytecode
    )
    vault_copy.contract_type.deployment_bytecode.bytecode = deploy_bytecode
    vault_copy.contract_type.name = f"{vault_copy.contract_type.name} Blueprint"

    blueprint_address = deployer.deploy(vault_copy, ZERO_ADDRESS, "", "", ZERO_ADDRESS, 0).address
    
    # deploy factory
    factory = deployer.deploy(vault_factory, "_TEST_ Vault V3 Factory", blueprint_address, max_priority_fee="1 gwei", max_fee="100 gwei", publish=publish_flag)
    
    # deploy first vault
    tx = factory.deploy_new_vault(ASSET_ADDRESS, "Yearn USDC V3", "yvUSDC", deployer.address, 7 * 24 * 3600,max_priority_fee="1 gwei", max_fee="100 gwei", sender=deployer)
    event = list(tx.decode_logs())
    vault = vault.at(event[0].vault_address)
    
    vault.set_role(deployer.address, ROLES.STRATEGY_MANAGER | ROLES.DEBT_MANAGER | ROLES.EMERGENCY_MANAGER | ROLES.ACCOUNTING_MANAGER, sender=deployer)
    
    # deploy debt lender
    debt_manager = deployer.deploy(debtmanager, vault.address, max_priority_fee="1 gwei", max_fee="100 gwei", sender=deployer)
    
    strategies = []
    
    # deploy Aave V2 strategy
    strategy_aave_v2 = deployer.deploy(strategy_aave_v2, vault.address, "AaveV2LenderUSDC", max_priority_fee="1 gwei", max_fee="100 gwei", publish=publish_flag)
    strategies.append(strategy_aave_v2)
    
    # deploy Comp V2 strategy
    strategy_comp_v2 = deployer.deploy(strategy_comp_v2, vault.address, "CompV2LenderUSDC", CASSET_ADDRESS, max_priority_fee="1 gwei", max_fee="100 gwei", publish=publish_flag)
    strategies.append(strategy_comp_v2)
    
    # deploy Comp V3 strategy
    strategy_comp_v3 = deployer.deploy(strategy_comp_v3, vault.address, "CompV3LenderUSDC", CASSETV3_ADDRESS, max_priority_fee="1 gwei", max_fee="100 gwei", publish=publish_flag)
    strategies.append(strategy_comp_v3)
    
    # set up
    total_assets = int(10_000 * int(10 ** vault.decimals()))
    debt_per_strategy = total_assets / len(strategies)
    vault.set_deposit_limit(total_assets, sender=deployer)
    # setup strategies
    for s in strategies:
        vault.add_strategy(s.address, max_priority_fee="1 gwei", max_fee="100 gwei", sender=deployer)
        debt_manager.addStrategy(s.address, max_priority_fee="1 gwei", max_fee="100 gwei", sender=deployer)
        vault.update_max_debt_for_strategy(s.address, int(total_assets), max_priority_fee="1 gwei", max_fee="100 gwei", sender=deployer)
     
    # TEST
    asset = Contract(ASSET_ADDRESS)
    whale = accounts[ASSET_WHALE_ADDRESS]
    asset.approve(vault.address, total_assets, sender=whale)
    vault.deposit(total_assets, whale.address, sender=whale)
    
    for s in strategies:
       vault.update_debt(s.address, int(debt_per_strategy), max_priority_fee="1 gwei", max_fee="100 gwei", sender=deployer)
       strat_name = s.name()
       strat_funds = vault.strategies(s.address).current_debt
       strat_assets = s.totalAssets()
       print(strat_name, strat_funds / (10 ** vault.decimals()), strat_assets / (10 ** vault.decimals()))
    
    tx = debt_manager.estimateAdjustPosition()
    print(tx.return_value)

    debt_manager.updateAllocations(sender=deployer).track_gas()

    for s in strategies: 
       strat_name = s.name()
       strat_funds = vault.strategies(s.address).current_debt
       strat_assets = s.totalAssets()

       print(strat_name, strat_funds / (10 ** vault.decimals()), strat_assets / (10 ** vault.decimals()))
